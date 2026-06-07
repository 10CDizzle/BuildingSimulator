import pygame
from pygame import gfxdraw
import random
import math
from config import settings  # For METERS_TO_PIXELS and colors


# ---------------------------------------------------------------------------
# Colour / drawing helpers
# ---------------------------------------------------------------------------

def _clamp8(v):
    return max(0, min(255, int(v)))


def lerp_color(c1, c2, t):
    """Linearly interpolate two RGB(A) colours by ``t`` in [0, 1]."""
    return tuple(_clamp8(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def scale_color(color, factor):
    """Multiply an RGB colour's brightness by ``factor`` (clamped)."""
    return tuple(_clamp8(c * factor) for c in color[:3])


def vertical_gradient(width, height, top_color, bottom_color, alpha=255):
    """A ``width`` x ``height`` surface shaded top-to-bottom.

    Built by colouring a 1-pixel-wide column and scaling it horizontally, which
    is far cheaper than per-pixel fills.
    """
    height = max(1, int(height))
    width = max(1, int(width))
    column = pygame.Surface((1, height), pygame.SRCALPHA)
    for y in range(height):
        t = y / max(1, height - 1)
        r, g, b = lerp_color(top_color, bottom_color, t)
        column.set_at((0, y), (r, g, b, alpha))
    return pygame.transform.smoothscale(column, (width, height))


def aa_polygon(surface, points, color):
    """Filled, anti-aliased polygon."""
    pts = [(int(round(x)), int(round(y))) for x, y in points]
    if len(pts) >= 3:
        gfxdraw.filled_polygon(surface, pts, color)
        gfxdraw.aapolygon(surface, pts, color)


def gradient_polygon(surface, points, top_color, bottom_color, alpha=255):
    """Fill an arbitrary polygon with a vertical gradient (handles sheared shapes)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = int(math.floor(min(xs))), int(math.ceil(max(xs)))
    min_y, max_y = int(math.floor(min(ys))), int(math.ceil(max(ys)))
    w = max(1, max_x - min_x)
    h = max(1, max_y - min_y)

    grad = vertical_gradient(w, h, top_color, bottom_color, alpha)
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    local = [(p[0] - min_x, p[1] - min_y) for p in points]
    aa_polygon(mask, local, (255, 255, 255, 255))
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(grad, (min_x, min_y))


def radial_glow(radius, color, max_alpha):
    """A soft circular glow surface, brightest in the centre."""
    radius = max(1, int(radius))
    surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    for r in range(radius, 0, -1):
        t = 1.0 - (r / radius)
        alpha = int(max_alpha * (t ** 2))
        gfxdraw.filled_circle(surf, radius, radius, r, (*color[:3], alpha))
    return surf


# Direction the key light comes from (upper-left), used for shading & shadows.
LIGHT_DIR = (-0.6, -0.8)


# ---------------------------------------------------------------------------
# Scene props
# ---------------------------------------------------------------------------

class Cloud:
    def __init__(self, x, y, width, height, speed):
        self.rect = pygame.Rect(x, y, width, height)
        self.speed = speed
        self.color = settings.CLOUD_COLOR
        self.num_puffs = random.randint(4, 6)
        self.puffs = []  # List of (rect, offset_x, offset_y)
        for _ in range(self.num_puffs):
            puff_w = random.randint(int(width * 0.4), int(width * 0.7))
            puff_h = random.randint(int(height * 0.5), int(height * 0.8))
            offset_x = random.randint(-int(width * 0.2), int(width * 0.2))
            offset_y = random.randint(-int(height * 0.2), int(height * 0.2))
            self.puffs.append((pygame.Rect(0, 0, puff_w, puff_h), offset_x, offset_y))
        self._sprite = None  # lazily-built soft sprite

    def _build_sprite(self):
        """Pre-render the cloud as soft, semi-transparent puffs (once)."""
        pad = 20
        w = self.rect.width + pad * 2
        h = self.rect.height + pad * 2
        # Overlapping puffs merge into one fluffy mass using normal alpha (not
        # additive, which would blow out the overlaps). Darker discs are laid
        # down first and offset downward so a soft shadow peeks out the bottom.
        mass = pygame.Surface((w, h), pygame.SRCALPHA)
        cx, cy = w // 2, h // 2
        shadow = scale_color(self.color, 0.75)
        for puff_rect, ox, oy in self.puffs:
            radius = max(puff_rect.width // 2, puff_rect.height // 2)
            disc = radial_glow(radius, shadow, 200)
            mass.blit(disc, (cx + ox - radius, cy + oy - radius + int(radius * 0.35)))
        for puff_rect, ox, oy in self.puffs:
            radius = max(puff_rect.width // 2, puff_rect.height // 2)
            disc = radial_glow(radius, self.color, 235)
            mass.blit(disc, (cx + ox - radius, cy + oy - radius))
        self._sprite = mass

    def draw(self, surface):
        if self._sprite is None:
            self._build_sprite()
        surface.blit(self._sprite, (self.rect.centerx - self._sprite.get_width() // 2,
                                    self.rect.centery - self._sprite.get_height() // 2))


class BuildingFragment:
    def __init__(self, initial_points_m, color, velocity_x_mps, velocity_y_mps, angular_velocity_rad_s):
        # initial_points_m: list of (x,y) tuples in meters, defining the polygon relative to world origin
        self.points_m = [list(p) for p in initial_points_m]  # Make points mutable
        self.center_m = self._calculate_centroid(self.points_m)

        # Translate points to be relative to the centroid for rotation
        for p in self.points_m:
            p[0] -= self.center_m[0]
            p[1] -= self.center_m[1]

        self.color = color
        self.pos_m = list(self.center_m)  # Current position of the centroid in meters
        self.velocity_x_mps = velocity_x_mps
        self.velocity_y_mps = velocity_y_mps
        self.angle_rad = 0.0
        self.angular_velocity_rad_s = angular_velocity_rad_s
        self.gravity_mps2 = 9.81
        self.is_settled = False
        self.min_y_for_settle = float('inf')  # Track lowest point for settling

    def _calculate_centroid(self, points):
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]
        return sum(x_coords) / len(points), sum(y_coords) / len(points)

    def update(self, delta_time, ground_y_at_x_func_pixels, biome_code):
        if self.is_settled:
            return

        self.velocity_y_mps += self.gravity_mps2 * delta_time
        self.pos_m[0] += self.velocity_x_mps * delta_time
        self.pos_m[1] += self.velocity_y_mps * delta_time
        self.angle_rad += self.angular_velocity_rad_s * delta_time

        # Basic ground collision and settling
        world_points_pixels = self.get_world_points_pixels()
        if not world_points_pixels:
            return

        fragment_bottom_center_x_pixels = self.pos_m[0] * settings.METERS_TO_PIXELS
        ground_level_pixels = ground_y_at_x_func_pixels(fragment_bottom_center_x_pixels, biome_code)

        if self.pos_m[1] * settings.METERS_TO_PIXELS > ground_level_pixels - 5:
            deepest_penetration = 0
            for _, py_pixel in world_points_pixels:
                if py_pixel > ground_level_pixels:
                    deepest_penetration = max(deepest_penetration, py_pixel - ground_level_pixels)

            if deepest_penetration > 0:
                self.pos_m[1] -= deepest_penetration / settings.METERS_TO_PIXELS
                self.velocity_y_mps *= -0.1
                self.velocity_x_mps *= 0.5
                self.angular_velocity_rad_s *= 0.3

                if abs(self.velocity_y_mps) < 0.2 and abs(self.angular_velocity_rad_s) < 0.05:
                    self.is_settled = True
                    self.velocity_y_mps = 0
                    self.velocity_x_mps = 0
                    self.angular_velocity_rad_s = 0

    def get_world_points_pixels(self):
        rotated_points_m = []
        cos_a, sin_a = math.cos(self.angle_rad), math.sin(self.angle_rad)
        for rel_x_m, rel_y_m in self.points_m:
            rotated_x = rel_x_m * cos_a - rel_y_m * sin_a
            rotated_y = rel_x_m * sin_a + rel_y_m * cos_a
            world_x_m = rotated_x + self.pos_m[0]
            world_y_m = rotated_y + self.pos_m[1]
            rotated_points_m.append((world_x_m * settings.METERS_TO_PIXELS, world_y_m * settings.METERS_TO_PIXELS))
        return rotated_points_m

    def draw(self, surface):
        world_points_pixels = self.get_world_points_pixels()
        if len(world_points_pixels) >= 3:
            top = scale_color(self.color, 1.18)
            bottom = scale_color(self.color, 0.7)
            gradient_polygon(surface, world_points_pixels, top, bottom)
            pts = [(int(round(x)), int(round(y))) for x, y in world_points_pixels]
            gfxdraw.aapolygon(surface, pts, scale_color(self.color, 0.45))


class RainParticle:
    def __init__(self, x_start, screen_height, speed_y, length, color=(190, 215, 235)):
        self.x = x_start
        self.y = random.randint(-screen_height // 4, 0)
        self.screen_height = screen_height
        self.speed_y = speed_y
        self.length = length
        self.color = color[:3]

    def update(self, delta_time):
        self.y += self.speed_y * delta_time
        if self.y > self.screen_height:
            self.y = random.randint(-self.screen_height // 4, -self.length)

    def draw(self, surface):
        pygame.draw.line(surface, self.color, (self.x, self.y), (self.x, self.y + self.length), 1)


class WindParticle:
    def __init__(self, screen_width, screen_height, velocity_mps):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.velocity_x_pixels_s = velocity_mps * settings.METERS_TO_PIXELS

        self.y = random.randint(0, screen_height)
        self.x = random.randint(-screen_width // 4, 0) if self.velocity_x_pixels_s > 0 else random.randint(screen_width, screen_width + screen_width // 4)

        self.length = max(8, abs(self.velocity_x_pixels_s) * 0.06)
        self.color = (220, 225, 235)

    def update(self, delta_time):
        self.x += self.velocity_x_pixels_s * delta_time
        if self.velocity_x_pixels_s > 0 and self.x > self.screen_width + self.length:
            self.x = -self.length
            self.y = random.randint(0, self.screen_height)
        elif self.velocity_x_pixels_s < 0 and self.x < -self.length:
            self.x = self.screen_width + self.length
            self.y = random.randint(0, self.screen_height)

    def draw(self, surface):
        start_pos = (self.x, self.y)
        end_pos = (self.x + self.length * math.copysign(1, self.velocity_x_pixels_s), self.y)
        pygame.draw.line(surface, self.color, start_pos, end_pos, 1)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class Renderer:
    def __init__(self, screen, biome_generator):
        self.screen = screen
        self.biome_generator = biome_generator
        self.width = screen.get_width()
        self.height = screen.get_height()
        self._backdrop_cache = {}  # biome_code -> pre-rendered sky/sun/hills surface
        # Reusable transparent layer for alpha particle batches.
        self._fx_layer = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

    # -- Backdrop (cached per biome) ----------------------------------------

    def _get_backdrop(self, biome_code):
        if biome_code in self._backdrop_cache:
            return self._backdrop_cache[biome_code]

        props = self.biome_generator.get_biome_properties(biome_code)
        sky = props["sky"]
        ground = props["ground"]
        w, h = self.width, self.height

        sky_top = scale_color(sky, 0.72)
        sky_horizon = lerp_color(sky, (255, 255, 255), 0.45)
        surf = vertical_gradient(w, h, sky_top, sky_horizon).convert()

        # Sun with a soft glow, biased to the light direction (upper-left).
        sun_x, sun_y = int(w * 0.20), int(h * 0.20)
        glow = radial_glow(int(h * 0.13), (255, 245, 215), 70)
        surf.blit(glow, (sun_x - glow.get_width() // 2, sun_y - glow.get_height() // 2),
                  special_flags=pygame.BLEND_RGBA_ADD)
        sun_r = int(h * 0.022)
        gfxdraw.filled_circle(surf, sun_x, sun_y, sun_r, (255, 250, 235))
        gfxdraw.aacircle(surf, sun_x, sun_y, sun_r, (255, 250, 235))

        # Distant parallax hills, fading toward the sky with atmospheric haze.
        base_y = h * props["base_height_factor"]
        for layer in range(3):
            depth = layer / 2.0  # 0 (far) .. 1 (near)
            hill_color = lerp_color(lerp_color(ground, sky_horizon, 0.65 - 0.2 * depth),
                                    ground, depth * 0.4)
            amplitude = 22 + 16 * depth
            frequency = 0.004 + 0.0016 * depth
            phase = layer * 1.7
            top = base_y - 60 + layer * 34
            pts = [(0, h)]
            for x in range(0, w + 1, 12):
                y = top + amplitude * math.sin(frequency * x + phase)
                pts.append((x, y))
            pts.append((w, h))
            aa_polygon(surf, pts, hill_color)

        # Gentle haze band along the horizon.
        haze = pygame.Surface((w, int(h * 0.12)), pygame.SRCALPHA)
        haze.fill((*sky_horizon, 70))
        surf.blit(haze, (0, int(base_y - h * 0.1)))

        self._backdrop_cache[biome_code] = surf
        return surf

    # -- Top-level scene ----------------------------------------------------

    def render_world(self, current_biome_code="Af", building_to_draw=None, building_x_position=None,
                     clouds=None, active_fragments=None, destruction_animation_playing=False,
                     liquefaction_effect_scale=0.0, wind_particles=None, rain_particles=None,
                     flood_water_surface_y_px=None):
        self.screen.blit(self._get_backdrop(current_biome_code), (0, 0))

        if clouds:
            self.render_clouds(clouds)

        ground_points = self.biome_generator.generate_ground_points(
            current_biome_code, liquefaction_effect_scale=liquefaction_effect_scale)
        self.render_ground(current_biome_code, ground_points)

        if wind_particles:
            self.render_wind_particles(wind_particles)

        if building_to_draw:
            if building_to_draw.is_destroyed:
                if destruction_animation_playing and active_fragments:
                    self.render_fragments(active_fragments)
                elif not destruction_animation_playing:
                    self.render_static_rubble_pile(building_to_draw, building_x_position,
                                                   current_biome_code, liquefaction_effect_scale)
            else:
                if building_x_position is not None:
                    self.render_building(building_to_draw, building_x_position,
                                         current_biome_code, liquefaction_effect_scale)

        if rain_particles:
            self.render_rain_particles(rain_particles)

        if flood_water_surface_y_px is not None:
            self.render_flood_water(flood_water_surface_y_px, ground_points)

    # -- Ground -------------------------------------------------------------

    def render_ground(self, biome_code, ground_points):
        props = self.biome_generator.get_biome_properties(biome_code)
        ground = props["ground"]
        surface_color = scale_color(ground, 1.25)
        deep_color = scale_color(ground, 0.55)

        gradient_polygon(self.screen, ground_points, surface_color, deep_color)

        # Bright grass/soil rim along the terrain crest for definition.
        crest = [p for p in ground_points if not (p[1] >= self.height - 1)]
        if len(crest) >= 2:
            rim = [(int(round(x)), int(round(y))) for x, y in crest]
            pygame.draw.aalines(self.screen, scale_color(ground, 1.5), False, rim)
            # A soft highlight just under the crest.
            shade = [(x, y + 3) for x, y in rim]
            pygame.draw.aalines(self.screen, scale_color(ground, 1.05), False, shade)

    # -- Clouds -------------------------------------------------------------

    def render_clouds(self, clouds):
        for cloud in clouds:
            cloud.draw(self.screen)

    # -- Building -----------------------------------------------------------

    def render_building(self, building, x_center_screen, biome_code, liquefaction_effect_scale=0.0):
        building_width_pixels = building.footprint_length * settings.METERS_TO_PIXELS
        building_height_pixels = building.total_height * settings.METERS_TO_PIXELS
        story_height_pixels = building.story_height * settings.METERS_TO_PIXELS

        building_x_left = x_center_screen - building_width_pixels / 2
        building_x_right = x_center_screen + building_width_pixels / 2

        ground_y_left = self.biome_generator.get_ground_y_at_x(building_x_left, biome_code, liquefaction_effect_scale)
        ground_y_right = self.biome_generator.get_ground_y_at_x(building_x_right, biome_code, liquefaction_effect_scale)

        max_angle_rad = math.radians(30)
        angle_rad = max(-max_angle_rad, min(max_angle_rad, building.angular_displacement_rad))
        top_shear_dx = building_height_pixels * math.tan(angle_rad)

        base_left = (building_x_left, ground_y_left)
        base_right = (building_x_right, ground_y_right)
        top_right = (building_x_right + top_shear_dx, ground_y_right - building_height_pixels)
        top_left = (building_x_left + top_shear_dx, ground_y_left - building_height_pixels)
        points = [base_left, base_right, top_right, top_left]

        # Ground contact shadow (soft ellipse) under the building.
        self._draw_contact_shadow(x_center_screen, (ground_y_left + ground_y_right) / 2,
                                  building_width_pixels)

        # Shaded body: lighter at the top, darker at the base.
        body = settings.GRAY
        gradient_polygon(self.screen, points, scale_color(body, 1.25), scale_color(body, 0.8))

        # Lit left edge highlight and shaded right edge for a sense of light.
        pygame.draw.aaline(self.screen, scale_color(body, 1.5), base_left, top_left)
        pygame.draw.aaline(self.screen, scale_color(body, 0.55), base_right, top_right)

        # Floor slab lines across the facade.
        for story_n in range(1, building.num_stories):
            frac = story_n / building.num_stories
            ly = (1 - frac)
            left = (building_x_left + top_shear_dx * frac,
                    ground_y_left - building_height_pixels * frac)
            right = (building_x_right + top_shear_dx * frac,
                     ground_y_right - building_height_pixels * frac)
            pygame.draw.aaline(self.screen, scale_color(body, 0.6), left, right)

        self._draw_windows(building, building_x_left, building_width_pixels,
                           ground_y_left, ground_y_right, story_height_pixels, angle_rad)

        # Crisp anti-aliased outline.
        gfxdraw.aapolygon(self.screen, [(int(round(x)), int(round(y))) for x, y in points],
                          scale_color(body, 0.4))

    def _draw_contact_shadow(self, x_center, ground_y, width):
        shadow = pygame.Surface((int(width * 1.6), 40), pygame.SRCALPHA)
        gfxdraw.filled_ellipse(shadow, shadow.get_width() // 2, 20,
                               int(width * 0.7), 14, (0, 0, 0, 90))
        self.screen.blit(shadow, (x_center - shadow.get_width() // 2, ground_y - 12))

    def _draw_windows(self, building, building_x_left, building_width_pixels,
                      ground_y_left, ground_y_right, story_height_pixels, angle_rad):
        num_windows = max(1, int(building.footprint_length / 5))
        window_width = story_height_pixels * 0.3
        window_height = story_height_pixels * 0.5
        window_margin_vertical = (story_height_pixels - window_height) / 2

        # Deterministic "lit" pattern per building so it doesn't flicker.
        rng = random.Random(building.num_stories * 131 + int(building.footprint_length))
        lit_warm = (255, 224, 150)
        glass_top = (200, 228, 240)
        glass_bottom = (120, 165, 195)

        for story_n in range(building.num_stories):
            story_base_y_left = ground_y_left - (story_n * story_height_pixels)
            story_base_y_right = ground_y_right - (story_n * story_height_pixels)
            for i in range(num_windows):
                win_x_offset = (i + 0.5) * (building_width_pixels / num_windows)
                original_center_x = building_x_left + win_x_offset
                slope_ratio = win_x_offset / building_width_pixels if building_width_pixels > 0 else 0
                win_base_y = story_base_y_left * (1 - slope_ratio) + story_base_y_right * slope_ratio
                win_top_y = win_base_y - story_height_pixels + window_margin_vertical

                center_height = (story_n + 0.5) * story_height_pixels
                shear_dx = center_height * math.tan(angle_rad)
                cx = original_center_x + shear_dx
                rect = pygame.Rect(cx - window_width / 2, win_top_y, window_width, window_height)

                if rng.random() < 0.28:
                    pygame.draw.rect(self.screen, lit_warm, rect)
                    glow = radial_glow(int(window_width), lit_warm, 60)
                    self.screen.blit(glow, (rect.centerx - glow.get_width() // 2,
                                            rect.centery - glow.get_height() // 2),
                                     special_flags=pygame.BLEND_RGBA_ADD)
                else:
                    grad = vertical_gradient(max(1, int(rect.width)), max(1, int(rect.height)),
                                             glass_top, glass_bottom)
                    self.screen.blit(grad, rect.topleft)
                    # Diagonal glass highlight.
                    pygame.draw.aaline(self.screen, (235, 245, 250),
                                       (rect.left + 2, rect.bottom - 3),
                                       (rect.left + rect.width * 0.55, rect.top + 2))
                pygame.draw.rect(self.screen, scale_color(settings.GRAY, 0.4), rect, 1)

    # -- Fragments / rubble -------------------------------------------------

    def render_fragments(self, fragments):
        for fragment in fragments:
            fragment.draw(self.screen)

    def render_static_rubble_pile(self, building, x_center_screen, biome_code, liquefaction_effect_scale=0.0):
        rubble_width_pixels = building.footprint_length * settings.METERS_TO_PIXELS * 1.2
        rubble_height_pixels = building.total_height * settings.METERS_TO_PIXELS * 0.2

        building_x_left = x_center_screen - rubble_width_pixels / 2
        building_x_right = x_center_screen + rubble_width_pixels / 2
        ground_y_left = self.biome_generator.get_ground_y_at_x(building_x_left, biome_code, liquefaction_effect_scale)
        ground_y_right = self.biome_generator.get_ground_y_at_x(building_x_right, biome_code, liquefaction_effect_scale)

        self._draw_contact_shadow(x_center_screen, (ground_y_left + ground_y_right) / 2,
                                  rubble_width_pixels)

        points = [
            (building_x_left, ground_y_left),
            (building_x_right, ground_y_right),
            (x_center_screen + rubble_width_pixels * 0.2, ground_y_right - rubble_height_pixels * 0.7),
            (x_center_screen, ground_y_left - rubble_height_pixels),
            (x_center_screen - rubble_width_pixels * 0.2, ground_y_left - rubble_height_pixels * 0.6),
        ]
        gradient_polygon(self.screen, points, scale_color(settings.GRAY, 1.1), scale_color(settings.GRAY, 0.7))
        gfxdraw.aapolygon(self.screen, [(int(round(x)), int(round(y))) for x, y in points],
                          scale_color(settings.GRAY, 0.4))

    # -- Weather particles --------------------------------------------------

    def render_wind_particles(self, wind_particles):
        self._fx_layer.fill((0, 0, 0, 0))
        for p in wind_particles:
            sign = math.copysign(1, p.velocity_x_pixels_s)
            head = (p.x + p.length * sign, p.y)
            tail = (p.x, p.y)
            pygame.draw.aaline(self._fx_layer, (*p.color, 130), tail, head)
        self.screen.blit(self._fx_layer, (0, 0))

    def render_rain_particles(self, rain_particles):
        self._fx_layer.fill((0, 0, 0, 0))
        # Slight wind-driven slant for liveliness.
        slant = 2
        for p in rain_particles:
            start = (p.x, p.y)
            end = (p.x + slant, p.y + p.length)
            pygame.draw.line(self._fx_layer, (*p.color, 150), start, end, 1)
        self.screen.blit(self._fx_layer, (0, 0))

    # -- Flood --------------------------------------------------------------

    def render_flood_water(self, water_surface_y_px, underlying_ground_points):
        """Render translucent flood water as a flat-topped body over the terrain.

        The water polygon runs along the flat surface line, then back along the
        terrain crest (reversed) so it correctly fills the gap between the water
        line and the ground.
        """
        if water_surface_y_px >= self.height - 1:
            return

        # Terrain crest points (exclude the two bottom-closing corners), left->right.
        crest = [p for p in underlying_ground_points if not (p[1] >= self.height - 1)]
        if len(crest) < 2:
            return

        water_poly = [(0, water_surface_y_px), (self.width, water_surface_y_px)]
        for x, y in reversed(crest):
            # Where terrain rises above the water line, clamp to the water surface.
            water_poly.append((x, max(y, water_surface_y_px)))

        layer = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        depth = self.height - water_surface_y_px
        top = (90, 170, 210, 120)
        bottom = (30, 90, 140, 180)
        # Gradient body clipped to the water polygon.
        grad = vertical_gradient(self.width, max(1, int(depth)), top[:3], bottom[:3], alpha=150)
        mask = pygame.Surface((self.width, max(1, int(depth))), pygame.SRCALPHA)
        local = [(x, y - water_surface_y_px) for x, y in water_poly]
        aa_polygon(mask, local, (255, 255, 255, 255))
        grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        layer.blit(grad, (0, water_surface_y_px))

        # Specular surface line with a subtle ripple, only where water exists
        # (i.e. where the terrain sits below the water line).
        def ground_y_at(x):
            prev = crest[0]
            for pt in crest[1:]:
                if prev[0] <= x <= pt[0]:
                    span = pt[0] - prev[0]
                    t = 0.0 if span == 0 else (x - prev[0]) / span
                    return prev[1] + (pt[1] - prev[1]) * t
                prev = pt
            return prev[1]

        segment = []
        for x in range(0, self.width + 1, 16):
            if ground_y_at(x) > water_surface_y_px:  # terrain is underwater here
                segment.append((x, water_surface_y_px + 1.5 * math.sin(x * 0.05)))
            elif len(segment) >= 2:
                pygame.draw.aalines(layer, (220, 240, 250, 200), False, segment)
                segment = []
            else:
                segment = []
        if len(segment) >= 2:
            pygame.draw.aalines(layer, (220, 240, 250, 200), False, segment)
        self.screen.blit(layer, (0, 0))

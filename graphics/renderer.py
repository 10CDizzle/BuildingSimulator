import pygame
import random
import math
from config import settings # For METERS_TO_PIXELS and colors

class Cloud:
    def __init__(self, x, y, width, height, speed):
        self.rect = pygame.Rect(x, y, width, height)
        self.speed = speed
        self.color = settings.CLOUD_COLOR
        # For a more "fluffy" look, a cloud can be a composite of several ellipses
        self.num_puffs = random.randint(3, 5)
        self.puffs = [] # List of (rect, offset_x, offset_y)
        for _ in range(self.num_puffs):
            puff_w = random.randint(int(width*0.4), int(width*0.7))
            puff_h = random.randint(int(height*0.5), int(height*0.8))
            offset_x = random.randint(-int(width*0.2), int(width*0.2))
            offset_y = random.randint(-int(height*0.2), int(height*0.2))
            self.puffs.append((pygame.Rect(0,0, puff_w, puff_h), offset_x, offset_y))

class BuildingFragment:
    def __init__(self, initial_points_m, color, velocity_x_mps, velocity_y_mps, angular_velocity_rad_s):
        # initial_points_m: list of (x,y) tuples in meters, defining the polygon relative to world origin
        self.points_m = [list(p) for p in initial_points_m] # Make points mutable
        self.center_m = self._calculate_centroid(self.points_m)
        
        # Translate points to be relative to the centroid for rotation
        for p in self.points_m:
            p[0] -= self.center_m[0]
            p[1] -= self.center_m[1]

        self.color = color
        self.pos_m = list(self.center_m) # Current position of the centroid in meters
        self.velocity_x_mps = velocity_x_mps
        self.velocity_y_mps = velocity_y_mps
        self.angle_rad = 0.0
        self.angular_velocity_rad_s = angular_velocity_rad_s
        self.gravity_mps2 = 9.81
        self.is_settled = False
        self.min_y_for_settle = float('inf') # Track lowest point for settling

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
        # Check the lowest point of the rotated fragment
        world_points_pixels = self.get_world_points_pixels()
        if not world_points_pixels: return # Should not happen if points exist

        current_min_y_pixels = min(p[1] for p in world_points_pixels)
        fragment_bottom_center_x_pixels = self.pos_m[0] * settings.METERS_TO_PIXELS # Approx.

        ground_level_pixels = ground_y_at_x_func_pixels(fragment_bottom_center_x_pixels, biome_code)

        if self.pos_m[1] * settings.METERS_TO_PIXELS > ground_level_pixels - 5: # If centroid is near/below ground
            # More robust check: if any point is below ground
            deepest_penetration = 0
            for _, py_pixel in world_points_pixels:
                 if py_pixel > ground_level_pixels:
                    deepest_penetration = max(deepest_penetration, py_pixel - ground_level_pixels)
            
            if deepest_penetration > 0:
                self.pos_m[1] -= deepest_penetration / settings.METERS_TO_PIXELS # Move fragment up
                self.velocity_y_mps *= -0.1 # Greatly reduce bounce
                self.velocity_x_mps *= 0.5  # Increase friction
                self.angular_velocity_rad_s *= 0.3 # Increase rotational friction

                if abs(self.velocity_y_mps) < 0.2 and abs(self.angular_velocity_rad_s) < 0.05: # Stricter settling condition
                    self.is_settled = True
                    self.velocity_y_mps = 0
                    self.velocity_x_mps = 0
                    self.angular_velocity_rad_s = 0

    def get_world_points_pixels(self):
        rotated_points_m = []
        for rel_x_m, rel_y_m in self.points_m:
            # Rotate point
            rotated_x = rel_x_m * math.cos(self.angle_rad) - rel_y_m * math.sin(self.angle_rad)
            rotated_y = rel_x_m * math.sin(self.angle_rad) + rel_y_m * math.cos(self.angle_rad)
            # Translate to world position (centroid)
            world_x_m = rotated_x + self.pos_m[0]
            world_y_m = rotated_y + self.pos_m[1]
            rotated_points_m.append((world_x_m * settings.METERS_TO_PIXELS, world_y_m * settings.METERS_TO_PIXELS))
        return rotated_points_m

    def draw(self, surface):
        world_points_pixels = self.get_world_points_pixels()
        if len(world_points_pixels) >= 3:
            pygame.draw.polygon(surface, self.color, world_points_pixels)
            pygame.draw.polygon(surface, settings.BLACK, world_points_pixels, 1) # Outline

class RainParticle:
    def __init__(self, x_start, screen_height, speed_y, length, color=(173, 216, 230, 180)): # Light blue, semi-transparent
        self.x = x_start
        self.y = random.randint(-screen_height // 4, 0) # Start above screen
        self.screen_height = screen_height
        self.speed_y = speed_y
        self.length = length
        self.color = color

    def update(self, delta_time):
        self.y += self.speed_y * delta_time
        if self.y > self.screen_height:
            self.y = random.randint(-self.screen_height // 4, -self.length) # Reset above screen
            # self.x can be re-randomized if you want rain to appear in different columns

    def draw(self, surface):
        pygame.draw.line(surface, self.color, (self.x, self.y), (self.x, self.y + self.length), 1)


class WindParticle:
    def __init__(self, screen_width, screen_height, velocity_mps):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.velocity_x_pixels_s = velocity_mps * settings.METERS_TO_PIXELS
        
        self.y = random.randint(0, screen_height)
        # Start off-screen, direction depends on velocity (assume positive velocity is left-to-right wind)
        self.x = random.randint(-screen_width // 4, 0) if self.velocity_x_pixels_s > 0 else random.randint(screen_width, screen_width + screen_width // 4)
        
        self.length = max(5, abs(self.velocity_x_pixels_s) * 0.05) # Length based on speed
        self.color = (200, 200, 220, 150) # Semi-transparent light grey/blue

    def update(self, delta_time):
        self.x += self.velocity_x_pixels_s * delta_time
        # Reset if off-screen
        if self.velocity_x_pixels_s > 0 and self.x > self.screen_width + self.length:
            self.x = -self.length
            self.y = random.randint(0, self.screen_height)
        elif self.velocity_x_pixels_s < 0 and self.x < -self.length:
            self.x = self.screen_width + self.length
            self.y = random.randint(0, self.screen_height)

    def draw(self, surface):
        # Draw as a short horizontal line
        start_pos = (self.x, self.y)
        end_pos = (self.x + self.length * math.copysign(1, self.velocity_x_pixels_s), self.y)
        pygame.draw.line(surface, self.color, start_pos, end_pos, 1)

class Renderer:
    def __init__(self, screen, biome_generator):
        """
        Initializes the Renderer.
        :param screen: The Pygame screen surface to draw on.
        :param biome_generator: An instance of BiomeGenerator.
        """
        self.screen = screen
        self.biome_generator = biome_generator
        # self.liquefaction_visuals_active = False # Replaced by liquefaction_effect_scale

    def render_world(self, current_biome_code="Af", building_to_draw=None, building_x_position=None, clouds=None, active_fragments=None, destruction_animation_playing=False, liquefaction_effect_scale=0.0, wind_particles=None, rain_particles=None, flood_water_surface_y_px=None):
        """
        Renders the game world based on the current biome.
        For a side view, this means a sky and a curvy ground.
        :param current_biome_code: The Koppen code for the biome to render.
        :param building_to_draw: Optional Building object to render.
        :param building_x_position: Optional x-coordinate for the center of the building.
        :param clouds: Optional list of Cloud objects to render.
        :param active_fragments: Optional list of BuildingFragment objects.
        :param destruction_animation_playing: Boolean indicating if destruction animation is active.
        :param liquefaction_effect_scale: Float (0.0 to 1.0) for ground deformation intensity.
        :param wind_particles: Optional list of WindParticle objects.
        :param rain_particles: Optional list of RainParticle objects.
        :param flood_water_surface_y_px: Optional Y-coordinate for the flood water surface.
        """
        biome_props = self.biome_generator.get_biome_properties(current_biome_code)
        sky_color = biome_props["sky"]
        ground_color = biome_props["ground"]

        self.screen.fill(sky_color)
        ground_points = self.biome_generator.generate_ground_points(current_biome_code, liquefaction_effect_scale=liquefaction_effect_scale)
        pygame.draw.polygon(self.screen, ground_color, ground_points)

        if flood_water_surface_y_px is not None:
            self.render_flood_water(flood_water_surface_y_px, ground_points, liquefaction_effect_scale)

        if wind_particles:
            self.render_wind_particles(wind_particles)
        
        if clouds:
            self.render_clouds(clouds)

        if rain_particles:
            self.render_rain_particles(rain_particles)

        if building_to_draw:
            if building_to_draw.is_destroyed:
                if destruction_animation_playing and active_fragments: # Render fragments during animation
                    self.render_fragments(active_fragments)
                elif not destruction_animation_playing: # Animation done, show static rubble
                    self.render_static_rubble_pile(building_to_draw, building_x_position, current_biome_code, liquefaction_effect_scale)
            else: # Building not destroyed
                if building_x_position is not None:
                    self.render_building(building_to_draw, building_x_position, current_biome_code, liquefaction_effect_scale)

    def render_clouds(self, clouds):
        """Renders a list of Cloud objects."""
        for cloud in clouds:
            # pygame.draw.ellipse(self.screen, cloud.color, cloud.rect) # Simple ellipse
            # Render composite puffs for a fluffier cloud
            for puff_rect_template, offset_x, offset_y in cloud.puffs:
                puff_rect = puff_rect_template.copy()
                puff_rect.centerx = cloud.rect.centerx + offset_x
                puff_rect.centery = cloud.rect.centery + offset_y
                pygame.draw.ellipse(self.screen, cloud.color, puff_rect)

    def render_building(self, building, x_center_screen, biome_code, liquefaction_effect_scale=0.0):
        """
        Renders a single building.
        :param building: The Building object to render.
        :param x_center_screen: The screen x-coordinate for the center of the building.
        :param biome_code: The current biome code to determine ground height.
        :param liquefaction_effect_scale: Float (0.0 to 1.0) for ground deformation intensity.
        """
        # This check is now handled in render_world to allow for animation
        # if building.is_destroyed:
        #     self.render_static_rubble_pile(building, x_center_screen, biome_code)
        #     return

        # Building dimensions in pixels
        building_width_pixels = building.footprint_length * settings.METERS_TO_PIXELS

        # Building dimensions in pixels
        building_width_pixels = building.footprint_length * settings.METERS_TO_PIXELS
        building_height_pixels = building.total_height * settings.METERS_TO_PIXELS
        story_height_pixels = building.story_height * settings.METERS_TO_PIXELS

        # Determine building's left and right x-coordinates
        building_x_left = x_center_screen - building_width_pixels / 2
        building_x_right = x_center_screen + building_width_pixels / 2

        # Get ground y-coordinates at the left and right edges of the building
        ground_y_left = self.biome_generator.get_ground_y_at_x(building_x_left, biome_code, liquefaction_effect_scale)
        ground_y_right = self.biome_generator.get_ground_y_at_x(building_x_right, biome_code, liquefaction_effect_scale)

        # Calculate horizontal shear displacement at the top due to angular displacement
        # Using tan for shear effect: dx = height * tan(angle)
        # Cap angle to prevent extreme deformation and math errors with tan
        max_angle_rad = math.radians(30) # Max 30 degrees lean
        angle_rad = max(-max_angle_rad, min(max_angle_rad, building.angular_displacement_rad))
        top_shear_dx = building_height_pixels * math.tan(angle_rad)

        # Define the four corner points of the building polygon
        points = [
            (building_x_left, ground_y_left),                                       # Bottom-left
            (building_x_right, ground_y_right),                                     # Bottom-right
            (building_x_right + top_shear_dx, ground_y_right - building_height_pixels), # Top-right (sheared)
            (building_x_left + top_shear_dx, ground_y_left - building_height_pixels),   # Top-left (sheared)
        ]

        pygame.draw.polygon(self.screen, settings.GRAY, points)
        pygame.draw.polygon(self.screen, settings.BLACK, points, 2) # Outline

        # --- Render Windows ---
        num_windows_per_story_per_side = max(1, int(building.footprint_length / 5)) # e.g., 1 window every 5m
        window_width = story_height_pixels * 0.3 # Window width as a fraction of story height
        window_height = story_height_pixels * 0.5 # Window height
        window_margin_horizontal = (building_width_pixels / num_windows_per_story_per_side - window_width) / 2
        window_margin_vertical = (story_height_pixels - window_height) / 2

        for story_n in range(building.num_stories):
            # Calculate y position for the bottom of the current story's windows
            # This needs to interpolate along the sloped base of the story
            story_base_y_left = ground_y_left - (story_n * story_height_pixels)
            story_base_y_right = ground_y_right - (story_n * story_height_pixels)

            for i in range(num_windows_per_story_per_side):
                # Original x position for the window center (relative to building's left edge)
                win_x_offset = (i + 0.5) * (building_width_pixels / num_windows_per_story_per_side)
                original_win_center_x_on_facade = building_x_left + win_x_offset

                # Interpolate y position for the window's base on the potentially sloped story
                slope_ratio = win_x_offset / building_width_pixels if building_width_pixels > 0 else 0
                win_base_y = story_base_y_left * (1 - slope_ratio) + story_base_y_right * slope_ratio
                win_top_y = win_base_y - story_height_pixels + window_margin_vertical
                
                # Calculate shear displacement at the window's vertical center
                # Height of window center from the building's base (approximate for sloped ground)
                window_center_height_from_avg_base = (story_n + 0.5) * story_height_pixels
                window_shear_dx = window_center_height_from_avg_base * math.tan(angle_rad)

                sheared_win_center_x = original_win_center_x_on_facade + window_shear_dx
                
                window_rect = pygame.Rect(sheared_win_center_x - window_width / 2, win_top_y, window_width, window_height)
                pygame.draw.rect(self.screen, settings.WINDOW_COLOR, window_rect)
                pygame.draw.rect(self.screen, settings.BLACK, window_rect, 1) # Window outline

    def render_fragments(self, fragments):
        """Renders active building fragments."""
        for fragment in fragments:
            fragment.draw(self.screen)

    def render_static_rubble_pile(self, building, x_center_screen, biome_code, liquefaction_effect_scale=0.0):
        """Renders a simple representation of a destroyed building."""
        rubble_width_pixels = building.footprint_length * settings.METERS_TO_PIXELS * 1.2
        rubble_height_pixels = building.total_height * settings.METERS_TO_PIXELS * 0.2

        building_x_left = x_center_screen - rubble_width_pixels / 2
        building_x_right = x_center_screen + rubble_width_pixels / 2
        # Use liquefaction status for ground level under rubble too
        ground_y_left = self.biome_generator.get_ground_y_at_x(building_x_left, biome_code, liquefaction_effect_scale)
        ground_y_right = self.biome_generator.get_ground_y_at_x(building_x_right, biome_code, liquefaction_effect_scale)
        
        # Simple rubble pile as a polygon
        points = [
            (building_x_left, ground_y_left),
            (building_x_right, ground_y_right),
            (x_center_screen + rubble_width_pixels * 0.2, ground_y_right - rubble_height_pixels * 0.7),
            (x_center_screen, ground_y_left - rubble_height_pixels), # Peak of rubble
            (x_center_screen - rubble_width_pixels * 0.2, ground_y_left - rubble_height_pixels * 0.6),
        ]
        pygame.draw.polygon(self.screen, settings.GRAY, points)
        pygame.draw.polygon(self.screen, settings.BLACK, points, 2)
        # Could add "DESTROYED" text here too

    def render_wind_particles(self, wind_particles):
        """Renders wind particles."""
        for particle in wind_particles:
            particle.draw(self.screen)

    def render_rain_particles(self, rain_particles):
        """Renders rain particles."""
        for particle in rain_particles:
            particle.draw(self.screen)

    def render_flood_water(self, water_surface_y_px, underlying_ground_points, liquefaction_effect_scale):
        """
        Renders flood water. The water surface is flat.
        :param water_surface_y_px: The y-coordinate of the flat water surface.
        :param underlying_ground_points: The points defining the current ground surface.
        :param liquefaction_effect_scale: Current scale of liquefaction for ground points.
        """
        if water_surface_y_px >= self.screen.get_height() -1: # No water visible or below screen
            return

        water_color = (64, 164, 223, 150) # Semi-transparent blue
        
        # Create a polygon for the water body
        water_poly_points = [(0, water_surface_y_px), (self.screen.get_width(), water_surface_y_px)]
        water_poly_points.extend(reversed([pt for pt in underlying_ground_points if pt[1] >= water_surface_y_px][:-2])) # Add ground points below water, in reverse
        
        if len(water_poly_points) > 2: # Need at least 3 points for a polygon
            # Create a temporary surface for transparency
            s = pygame.Surface((self.screen.get_width(), self.screen.get_height()), pygame.SRCALPHA)
            pygame.draw.polygon(s, water_color, water_poly_points)
            self.screen.blit(s, (0,0))
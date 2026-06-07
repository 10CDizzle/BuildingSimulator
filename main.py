import random
import pygame
import pygame_gui

from config import settings
from graphics.renderer import Renderer, Cloud, WindParticle, RainParticle
from core.biome_generator import BiomeGenerator
from core import physics
from core.building_structure import (
    Building, CONCRETE, STEEL, WOOD, StructuralSystemType, MassDistribution,
)

# --- Option maps shared between the UI and the model ------------------------

MATERIALS = {"Concrete": CONCRETE, "Steel": STEEL, "Wood": WOOD}
SYSTEMS = {
    "Moment Frame": StructuralSystemType.FRAME_MOMENT_RESISTING,
    "Braced (Conc.)": StructuralSystemType.FRAME_BRACED_CONCENTRIC,
    "Braced (Ecc.)": StructuralSystemType.FRAME_BRACED_ECCENTRIC,
    "Shear Walls": StructuralSystemType.SHEAR_WALLS,
    "Core Wall": StructuralSystemType.CORE_WALL,
    "Diagrid": StructuralSystemType.DIAGRID,
}
SOILS = {
    "Rock": physics.ROCK_SOIL,
    "Firm": physics.FIRM_SOIL,
    "Medium": physics.MEDIUM_SOIL,
    "Soft": physics.SOFT_SOIL,
}
MOTIONS = ["Synthetic", "Harmonic"]


def main():
    pygame.init()
    screen = pygame.display.set_mode((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    pygame.display.set_caption("2D Building Simulator")
    clock = pygame.time.Clock()
    info_font = pygame.font.SysFont("Consolas", 20)
    small_font = pygame.font.SysFont("Consolas", 16)

    biome_generator = BiomeGenerator(settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT)
    renderer = Renderer(screen, biome_generator)
    ui = pygame_gui.UIManager((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), 'config/theme.json')

    W, H = settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT

    # --- UI construction helpers -------------------------------------------
    def label(x, y, w, text, container=None):
        return pygame_gui.elements.UILabel(pygame.Rect((x, y), (w, 20)), text, manager=ui)

    def slider(x, y, w, start, rng):
        return pygame_gui.elements.UIHorizontalSlider(
            pygame.Rect((x, y), (w, 22)), start_value=start, value_range=rng, manager=ui)

    def dropdown(x, y, w, options, start):
        return pygame_gui.elements.UIDropDownMenu(options, start, pygame.Rect((x, y), (w, 26)), manager=ui)

    def button(x, y, w, text):
        return pygame_gui.elements.UIButton(pygame.Rect((x, y), (w, 30)), text, manager=ui)

    # --- Left column: structure --------------------------------------------
    lx, lw = 12, 210
    y = 10
    label(lx, y, lw, "— STRUCTURE —"); y += 22
    label(lx, y, lw, "Stories"); y += 18
    s_stories = slider(lx, y, lw, 8, (1, 18)); y += 26
    label(lx, y, lw, "Story Height (m)"); y += 18
    s_story_h = slider(lx, y, lw, 3.5, (2.5, 4.0)); y += 26
    label(lx, y, lw, "Length (m)"); y += 18
    s_length = slider(lx, y, lw, 22, (8, 50)); y += 26
    label(lx, y, lw, "Width (m)"); y += 18
    s_width = slider(lx, y, lw, 16, (8, 50)); y += 26
    label(lx, y, lw, "Ductility"); y += 18
    s_ductility = slider(lx, y, lw, 0.6, (0.0, 1.0)); y += 28
    label(lx, y, lw, "Material"); y += 18
    d_material = dropdown(lx, y, lw, list(MATERIALS), "Concrete"); y += 30
    label(lx, y, lw, "System"); y += 18
    d_system = dropdown(lx, y, lw, list(SYSTEMS), "Moment Frame"); y += 30
    label(lx, y, lw, "Soil"); y += 18
    d_soil = dropdown(lx, y, lw, list(SOILS), "Firm"); y += 30

    # --- Right column: hazards ---------------------------------------------
    rx, rw = W - 222, 210
    y = 10
    label(rx, y, rw, "— HAZARDS —"); y += 22
    label(rx, y, rw, "Wind Speed (m/s)"); y += 18
    s_wind = slider(rx, y, rw, 25, (0, 80)); y += 26
    b_wind = button(rx, y, rw, "Start Wind"); y += 36
    label(rx, y, rw, "Earthquake PGA (g)"); y += 18
    s_pga = slider(rx, y, rw, 0.3, (0.0, 1.0)); y += 26
    label(rx, y, rw, "Ground Motion"); y += 18
    d_motion = dropdown(rx, y, rw, MOTIONS, "Synthetic"); y += 30
    b_quake = button(rx, y, rw, "Trigger Quake"); y += 36
    label(rx, y, rw, "Rainfall (mm/hr)"); y += 18
    s_rain = slider(rx, y, rw, 80, (0, 200)); y += 26
    b_rain = button(rx, y, rw, "Start Rainfall"); y += 30

    # --- Model construction -------------------------------------------------
    selected_soil = [SOILS["Firm"]]  # the user's chosen soil (liquefaction swaps temporarily)

    def make_building():
        return Building(
            num_stories=int(s_stories.get_current_value()),
            story_height=round(s_story_h.get_current_value(), 2),
            footprint_length=round(s_length.get_current_value(), 1),
            footprint_width=round(s_width.get_current_value(), 1),
            primary_material=MATERIALS[d_material.selected_option[0] if isinstance(d_material.selected_option, tuple) else d_material.selected_option],
            structural_system=SYSTEMS[d_system.selected_option[0] if isinstance(d_system.selected_option, tuple) else d_system.selected_option],
            ductility_level=round(s_ductility.get_current_value(), 2),
            soil_profile=selected_soil[0],
        )

    building = make_building()
    base_center_x = W // 2

    # --- Scene props --------------------------------------------------------
    clouds = []
    for _ in range(6):
        cw = random.randint(90, 200)
        ch = random.randint(45, 90)
        cx = random.randint(0, W)
        cy = random.randint(20, H // 3)
        spd = random.uniform(0.3, 1.2) * random.choice([-1, 1])
        clouds.append(Cloud(cx, cy, cw, ch, spd))

    available_biomes = biome_generator.get_available_biomes()
    current_biome = random.choice(available_biomes) if available_biomes else "Dfc"

    # --- Mutable run state --------------------------------------------------
    model_dirty = False
    sim_time = 0.0

    wind_on = False
    wind_load = [None]

    quake_active = False
    quake_t = 0.0
    ground_motion = [None]
    liquefied = False

    rain_on = False
    water_level_m = 0.0
    wind_particles = []
    rain_particles = []

    # Destruction state
    destruction_playing = False
    fragments = []
    destruction_timer = 0.0
    dialog = None

    def rebuild():
        nonlocal building, wind_load, liquefied
        building = make_building()
        if wind_on:
            wind_load[0] = physics.WindLoad(building, s_wind.get_current_value())
        liquefied = False

    def start_quake():
        nonlocal quake_active, quake_t, liquefied
        pga = s_pga.get_current_value()
        motion = d_motion.selected_option[0] if isinstance(d_motion.selected_option, tuple) else d_motion.selected_option
        if motion == "Harmonic":
            ground_motion[0] = physics.HarmonicGroundMotion(pga_g=pga, frequency_hz=1.5, duration=10.0)
        else:
            ground_motion[0] = physics.SyntheticGroundMotion(pga_g=pga, duration=18.0, seed=random.randint(0, 9999))
        quake_active = True
        quake_t = 0.0
        # Strong shaking liquefies the chosen soil for the duration of the event.
        if pga >= 0.4 and not liquefied:
            building.set_soil_profile(selected_soil[0].with_shear_modulus_factor(0.05))
            liquefied = True

    def end_quake():
        nonlocal quake_active, liquefied
        quake_active = False
        if liquefied:
            building.set_soil_profile(selected_soil[0])
            liquefied = False

    def spawn_wind_particles():
        wind_particles.clear()
        speed = s_wind.get_current_value()
        if speed > 0.1:
            for _ in range(min(int(speed * 1.5), 150)):
                wind_particles.append(WindParticle(W, H, speed))

    def spawn_rain_particles():
        rain_particles.clear()
        intensity = s_rain.get_current_value()
        for _ in range(min(int(intensity * 1.5), 320)):
            x = random.randint(0, W)
            rain_particles.append(RainParticle(x, H, random.uniform(450, 700), random.uniform(8, 16)))

    running = True
    while running:
        dt = clock.tick(settings.FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

            ui.process_events(event)

            if event.type == pygame_gui.UI_HORIZONTAL_SLIDER_MOVED:
                if event.ui_element in (s_stories, s_story_h, s_length, s_width, s_ductility):
                    model_dirty = True
                elif event.ui_element is s_wind and wind_on:
                    wind_load[0] = physics.WindLoad(building, s_wind.get_current_value())
                    spawn_wind_particles()

            elif event.type == pygame_gui.UI_DROP_DOWN_MENU_CHANGED:
                if event.ui_element is d_soil:
                    selected_soil[0] = SOILS[event.text]
                    model_dirty = True
                elif event.ui_element in (d_material, d_system):
                    model_dirty = True

            elif event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element is b_wind:
                    wind_on = not wind_on
                    b_wind.set_text("Stop Wind" if wind_on else "Start Wind")
                    if wind_on:
                        wind_load[0] = physics.WindLoad(building, s_wind.get_current_value())
                        spawn_wind_particles()
                    else:
                        wind_load[0] = None
                        wind_particles.clear()
                elif event.ui_element is b_quake and not building.is_destroyed:
                    start_quake()
                elif event.ui_element is b_rain:
                    rain_on = not rain_on
                    b_rain.set_text("Stop Rainfall" if rain_on else "Start Rainfall")
                    if rain_on:
                        spawn_rain_particles()
                    else:
                        rain_particles.clear()

            elif event.type == pygame_gui.UI_CONFIRMATION_DIALOG_CONFIRMED and event.ui_element is dialog:
                # Reset to a fresh building of the current settings.
                wind_on = False
                b_wind.set_text("Start Wind")
                rain_on = False
                b_rain.set_text("Start Rainfall")
                water_level_m = 0.0
                rain_particles.clear()
                wind_particles.clear()
                rebuild()
                dialog = None

        # Batch geometry rebuilds to once per frame.
        if model_dirty and not destruction_playing:
            rebuild()
            model_dirty = False

        ui.update(dt)
        sim_time += dt

        # --- Drive the simulation ------------------------------------------
        liq_visual = 0.0
        if not destruction_playing and not building.is_destroyed:
            ground_accel = 0.0
            if quake_active:
                ground_accel = ground_motion[0](quake_t)
                quake_t += dt
                if liquefied:
                    liq_visual = min(1.0, (s_pga.get_current_value() - 0.4) / 0.6 + 0.3)
                if quake_t > ground_motion[0].duration:
                    end_quake()

            wind_force = wind_load[0].force_at(sim_time) if (wind_on and wind_load[0] is not None) else None

            if rain_on:
                water_level_m += (s_rain.get_current_value() / 100.0) * 0.4 * dt
            else:
                water_level_m = max(0.0, water_level_m - 0.05 * dt)
            flood_force = physics.flood_lateral_force(building, water_level_m) if water_level_m > 0.01 else None

            building.update_physics(dt, ground_accel, wind_force, flood_force)

            if building.is_destroyed and not destruction_playing:
                destruction_playing = True
                destruction_timer = 0.0
                base_x_m = base_center_x / settings.METERS_TO_PIXELS
                ground_y_px = biome_generator.get_ground_y_at_x(base_center_x, current_biome, liq_visual)
                base_y_m = ground_y_px / settings.METERS_TO_PIXELS
                fragments = building.generate_fragments(base_x_m, base_y_m, building.angular_displacement_rad)

        # --- Update scene props --------------------------------------------
        for cloud in clouds:
            cloud.rect.x += cloud.speed
            if cloud.speed > 0 and cloud.rect.left > W:
                cloud.rect.right = 0
                cloud.rect.y = random.randint(20, H // 3)
            elif cloud.speed < 0 and cloud.rect.right < 0:
                cloud.rect.left = W
                cloud.rect.y = random.randint(20, H // 3)
        for p in wind_particles:
            p.update(dt)
        for p in rain_particles:
            p.update(dt)

        if destruction_playing:
            destruction_timer += dt
            all_settled = bool(fragments)
            for frag in fragments:
                frag.update(dt, biome_generator.get_ground_y_at_x, current_biome)
                if not frag.is_settled:
                    all_settled = False
            if (all_settled and fragments) or destruction_timer > 5.0:
                destruction_playing = False
                if dialog is None:
                    dialog = pygame_gui.windows.UIConfirmationDialog(
                        rect=pygame.Rect((W // 2 - 160, H // 2 - 100), (320, 200)),
                        manager=ui, window_title="Building Collapsed!",
                        action_long_desc="The structure has failed. Rebuild and try again?",
                        action_short_name="Rebuild", blocking=True)

        # --- Render ---------------------------------------------------------
        base_ground_y = biome_generator.get_ground_y_at_x(base_center_x, current_biome, liq_visual)
        flood_surface_y = base_ground_y - water_level_m * settings.METERS_TO_PIXELS
        renderer.render_world(
            current_biome, building, base_center_x, clouds=clouds,
            active_fragments=fragments, destruction_animation_playing=destruction_playing,
            liquefaction_effect_scale=liq_visual, wind_particles=wind_particles,
            rain_particles=rain_particles,
            flood_water_surface_y_px=(flood_surface_y if water_level_m > 0.01 else None))

        draw_readout(screen, info_font, small_font, building, quake_active, water_level_m, liquefied)
        ui.draw_ui(screen)
        pygame.display.flip()

    pygame.quit()


def draw_readout(screen, font, small_font, building, quake_active, water_level_m, liquefied):
    """Live structural-response readout across the top-centre of the screen."""
    cap = building.drift_capacity
    drift = building.max_drift_ratio
    ratio = drift / cap if cap > 0 else 0.0

    if building.is_destroyed:
        status, color = "COLLAPSED", (235, 70, 60)
    elif building.num_failed_stories > 0:
        status, color = f"{building.num_failed_stories} STORY HINGED", (240, 170, 60)
    else:
        status, color = "INTACT", (120, 220, 130)

    if ratio < 0.5:
        drift_color = (120, 220, 130)
    elif ratio < 1.0:
        drift_color = (240, 200, 70)
    else:
        drift_color = (235, 70, 60)

    cx = settings.SCREEN_WIDTH // 2
    line1 = f"T1 = {building.fundamental_period:.2f} s    mass {building.calculated_mass/1e3:,.0f} t"
    surf1 = font.render(line1, True, (245, 245, 245))
    screen.blit(surf1, (cx - surf1.get_width() // 2, 12))

    drift_txt = small_font.render(f"max drift {100*drift:.2f}%  (capacity {100*cap:.2f}%)", True, drift_color)
    screen.blit(drift_txt, (cx - drift_txt.get_width() // 2, 36))

    status_surf = font.render(status, True, color)
    screen.blit(status_surf, (cx - status_surf.get_width() // 2, 56))

    tags = []
    if quake_active:
        tags.append("SHAKING")
    if liquefied:
        tags.append("LIQUEFACTION")
    if water_level_m > 0.01:
        tags.append(f"FLOOD {water_level_m:.1f} m")
    if tags:
        tag_surf = small_font.render("  ".join(tags), True, (200, 220, 255))
        screen.blit(tag_surf, (cx - tag_surf.get_width() // 2, 80))


if __name__ == "__main__":
    main()

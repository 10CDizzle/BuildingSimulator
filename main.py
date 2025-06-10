import pygame
import random
from config import settings
from graphics.renderer import Renderer, Cloud # Import Cloud
from core.biome_generator import BiomeGenerator
from core.building_structure import Building, CONCRETE # Import Building and an example material
import pygame_gui


def main():
    pygame.init()

    screen = pygame.display.set_mode((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    pygame.display.set_caption("2D Building Simulator")
    clock = pygame.time.Clock()

    # Instantiate BiomeGenerator
    biome_generator = BiomeGenerator(settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT)
    # Pass biome_generator to Renderer
    renderer = Renderer(screen, biome_generator)

    # --- Pygame GUI Manager ---
    ui_manager = pygame_gui.UIManager((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), 'config/theme.json')
    ui_margin = 20
    slider_height = 30 # pygame_gui elements might have different preferred heights
    slider_width = 220
    label_height = 20
    label_width = slider_width

    # Initial building parameters
    initial_stories = 5
    initial_story_h = 3.0
    initial_length = 15.0
    initial_width = 10.0

    # --- Create UI Elements ---
    # Stories Slider
    pygame_gui.elements.UILabel(relative_rect=pygame.Rect((ui_margin, settings.SCREEN_HEIGHT - slider_height * 4 - ui_margin - label_height), (label_width, label_height)), text="Stories:", manager=ui_manager)
    stories_slider = pygame_gui.elements.UIHorizontalSlider(relative_rect=pygame.Rect((ui_margin, settings.SCREEN_HEIGHT - slider_height * 4 - ui_margin), (slider_width, slider_height)), start_value=initial_stories, value_range=(1, 20), manager=ui_manager, object_id="#stories_slider")
    # Story Height Slider
    pygame_gui.elements.UILabel(relative_rect=pygame.Rect((ui_margin, settings.SCREEN_HEIGHT - slider_height * 3 - ui_margin - label_height), (label_width, label_height)), text="Story Height (m):", manager=ui_manager)
    story_h_slider = pygame_gui.elements.UIHorizontalSlider(relative_rect=pygame.Rect((ui_margin, settings.SCREEN_HEIGHT - slider_height * 3 - ui_margin), (slider_width, slider_height)), start_value=initial_story_h, value_range=(2.0, 5.0), manager=ui_manager, object_id="#story_h_slider")
    # Footprint Length Slider
    pygame_gui.elements.UILabel(relative_rect=pygame.Rect((ui_margin, settings.SCREEN_HEIGHT - slider_height * 2 - ui_margin - label_height), (label_width, label_height)), text="Length (m):", manager=ui_manager)
    length_slider = pygame_gui.elements.UIHorizontalSlider(relative_rect=pygame.Rect((ui_margin, settings.SCREEN_HEIGHT - slider_height * 2 - ui_margin), (slider_width, slider_height)), start_value=initial_length, value_range=(5.0, 50.0), manager=ui_manager, object_id="#length_slider")
    # Footprint Width Slider
    pygame_gui.elements.UILabel(relative_rect=pygame.Rect((ui_margin, settings.SCREEN_HEIGHT - slider_height * 1 - ui_margin - label_height), (label_width, label_height)), text="Width (m):", manager=ui_manager)
    width_slider = pygame_gui.elements.UIHorizontalSlider(relative_rect=pygame.Rect((ui_margin, settings.SCREEN_HEIGHT - slider_height * 1 - ui_margin), (slider_width, slider_height)), start_value=initial_width, value_range=(5.0, 50.0), manager=ui_manager, object_id="#width_slider")

    # Event Button
    button_width = 150
    button_height = 40
    simulate_wind_button = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((settings.SCREEN_WIDTH - button_width - ui_margin, settings.SCREEN_HEIGHT - button_height - ui_margin), (button_width, button_height)), text='Simulate Wind', manager=ui_manager, object_id="#wind_button")

    # Store sliders for easy access if needed, or use object_ids
    sliders = {
        "stories": stories_slider,
        "story_h": story_h_slider,
        "length": length_slider,
        "width": width_slider
    }

    # --- Create a sample building ---
    sample_building = Building(
        num_stories=initial_stories,
        story_height=initial_story_h,
        footprint_length=initial_length, # meters
        footprint_width=initial_width,  # meters
        primary_material=CONCRETE,
        # Adjust these values to get desired sway behavior
        rotational_stiffness_nm_per_rad=8e7, # Higher stiffness
        rotational_damping_nm_s_per_rad=5e6   # Moderate damping
    )
    building_base_screen_x_center = settings.SCREEN_WIDTH // 2 # Base position of the building

    # --- Cloud Management ---
    clouds = []
    MAX_CLOUDS = 7
    CLOUD_MIN_SPEED = 0.5
    CLOUD_MAX_SPEED = 1.5

    def create_cloud():
        width = random.randint(80, 200)
        height = random.randint(40, 100)
        # Start off-screen to the right or left
        x = random.choice([-width, settings.SCREEN_WIDTH]) 
        y = random.randint(20, settings.SCREEN_HEIGHT // 3) # Clouds in the upper third
        speed = random.uniform(CLOUD_MIN_SPEED, CLOUD_MAX_SPEED)
        if x > settings.SCREEN_WIDTH / 2: # If starting on right, move left
            speed = -speed
        return Cloud(x, y, width, height, speed)

    for _ in range(MAX_CLOUDS):
        clouds.append(create_cloud())

    # --- Game State ---
    current_biome = "Dfc" # Example: Hot Desert

    running = True
    while running:
        time_delta = clock.tick(settings.FPS) / 1000.0 # time_delta in seconds
        event_list = pygame.event.get()
        # --- Event Handling ---
        for event in event_list:
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
        
            ui_manager.process_events(event) # Pass events to pygame_gui

            # Handle UI events
            if event.type == pygame_gui.UI_HORIZONTAL_SLIDER_MOVED:
                parameter_changed = False
                if event.ui_element == stories_slider:
                    sample_building.num_stories = int(event.value)
                    parameter_changed = True
                elif event.ui_element == story_h_slider:
                    sample_building.story_height = round(event.value, 1)
                    parameter_changed = True
                elif event.ui_element == length_slider:
                    sample_building.footprint_length = round(event.value, 1)
                    parameter_changed = True
                elif event.ui_element == width_slider:
                    sample_building.footprint_width = round(event.value, 1)
                    parameter_changed = True
                
                if parameter_changed: # Recalculate derived properties and mass
                    sample_building.total_height = sample_building.num_stories * sample_building.story_height
                    sample_building.aspect_ratio_l = sample_building.total_height / sample_building.footprint_length if sample_building.footprint_length > 0 else float('inf')
                    sample_building.aspect_ratio_w = sample_building.total_height / sample_building.footprint_width if sample_building.footprint_width > 0 else float('inf')
                    sample_building.calculated_mass = sample_building._calculate_total_mass() # Recalculate mass
                    if sample_building.calculated_mass <= 0: sample_building.calculated_mass = 1000 # Safety
                    # Recalculate moment of inertia as mass and height might have changed
                    sample_building.moment_of_inertia_kg_m2 = (1/3) * sample_building.calculated_mass * (sample_building.total_height**2) if sample_building.total_height > 0 else 1e6

            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == simulate_wind_button:
                    wind_speed_mps = random.uniform(15.0, 40.0) # Simulate wind speed (m/s)
                    print(f"Simulating wind at {wind_speed_mps:.1f} m/s")
                    
                    # Calculate wind force: F = 0.5 * rho * v^2 * A * Cd
                    # Exposed area (simplified as frontal area: height * width)
                    # For a 2D side view, we use footprint_length as the "width" exposed to wind.
                    exposed_area = sample_building.total_height * sample_building.footprint_length 
                    wind_force_newtons = 0.5 * settings.AIR_DENSITY * (wind_speed_mps**2) * exposed_area * settings.DEFAULT_DRAG_COEFFICIENT
                    
                    # Apply force at mid-height of the building
                    sample_building.apply_horizontal_force(wind_force_newtons, sample_building.total_height / 2)

        # --- Game Logic - Update Clouds ---
        for cloud in clouds:
            cloud.rect.x += cloud.speed
            # If cloud moves off screen, reset it
            if cloud.speed > 0 and cloud.rect.left > settings.SCREEN_WIDTH:
                cloud.rect.right = 0
                cloud.rect.y = random.randint(20, settings.SCREEN_HEIGHT // 3)
            elif cloud.speed < 0 and cloud.rect.right < 0:
                cloud.rect.left = settings.SCREEN_WIDTH
                cloud.rect.y = random.randint(20, settings.SCREEN_HEIGHT // 3)

        # --- Game Logic - Update Building Physics ---
        sample_building.update_physics(time_delta)

        ui_manager.update(time_delta)

        # --- Rendering ---
        renderer.render_world(current_biome, sample_building, building_base_screen_x_center, clouds)
        ui_manager.draw_ui(screen) # Draw pygame_gui elements

        pygame.display.flip()

        # clock.tick(settings.FPS) # time_delta is already handled by clock.tick

    pygame.quit()

if __name__ == "__main__":
    main()
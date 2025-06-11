import pygame
import random
import math # Import the math module
from config import settings
from graphics.renderer import Renderer, Cloud, BuildingFragment # Import BuildingFragment
from core.biome_generator import BiomeGenerator # Import BiomeGenerator
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
    initial_wind_speed = 25.0 # m/s

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

    # Wind Speed Slider (placing it next to the button or above it)
    pygame_gui.elements.UILabel(relative_rect=pygame.Rect((settings.SCREEN_WIDTH - slider_width - ui_margin, settings.SCREEN_HEIGHT - slider_height * 2 - ui_margin - label_height), (label_width, label_height)), text="Wind Speed (m/s):", manager=ui_manager)
    wind_speed_slider = pygame_gui.elements.UIHorizontalSlider(relative_rect=pygame.Rect((settings.SCREEN_WIDTH - slider_width - ui_margin, settings.SCREEN_HEIGHT - slider_height * 2 - ui_margin), (slider_width, slider_height)), start_value=initial_wind_speed, value_range=(0.0, 6000.0), manager=ui_manager, object_id="#wind_speed_slider")

    # Event Button
    action_button_width = 150
    button_height = 40
    simulate_wind_button = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((settings.SCREEN_WIDTH - action_button_width - ui_margin, settings.SCREEN_HEIGHT - slider_height * 1 - ui_margin), (action_button_width, button_height)), text='Simulate Wind', manager=ui_manager, object_id="#wind_button")

    # Earthquake Intensity Slider
    initial_earthquake_intensity = 0.2 # PGA in g (e.g., 0.2g)
    pygame_gui.elements.UILabel(relative_rect=pygame.Rect((settings.SCREEN_WIDTH - slider_width - ui_margin, settings.SCREEN_HEIGHT - slider_height * 4 - ui_margin - label_height), (label_width, label_height)), text="Tremor Intensity (PGA g):", manager=ui_manager)
    earthquake_intensity_slider = pygame_gui.elements.UIHorizontalSlider(relative_rect=pygame.Rect((settings.SCREEN_WIDTH - slider_width - ui_margin, settings.SCREEN_HEIGHT - slider_height * 4 - ui_margin), (slider_width, slider_height)), start_value=initial_earthquake_intensity, value_range=(0.0, 1.0), manager=ui_manager, object_id="#earthquake_intensity_slider")
    # Earthquake Button
    simulate_earthquake_button = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((settings.SCREEN_WIDTH - action_button_width - ui_margin, settings.SCREEN_HEIGHT - slider_height * 3 - ui_margin), (action_button_width, button_height)), text='Simulate Earthquake', manager=ui_manager, object_id="#earthquake_button")


    # Store sliders for easy access if needed, or use object_ids
    sliders = {
        "stories": stories_slider,
        "story_h": story_h_slider,
        "length": length_slider,
        "width": width_slider
    }

    # --- Function to create/reset the building ---
    def create_new_building():
        return Building(
            num_stories=int(stories_slider.get_current_value()),
            story_height=round(story_h_slider.get_current_value(), 1),
            footprint_length=round(length_slider.get_current_value(), 1),
            footprint_width=round(width_slider.get_current_value(), 1),
            primary_material=CONCRETE, # Or allow selection later
            rotational_stiffness_nm_per_rad=8e7, # Default, could be UI controlled
            rotational_damping_nm_s_per_rad=5e6,   # Default, could be UI controlled
            max_safe_angular_displacement_rad=settings.DEFAULT_MAX_SAFE_ANGLE_RAD
        )

    sample_building = create_new_building()
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
    game_over_prompt_active = False
    destruction_animation_playing = False
    active_fragments = [] # Changed from active_debris
    destruction_animation_timer = 0.0
    confirmation_dialog = None

    earthquake_active = False
    earthquake_timer = 0.0
    earthquake_duration = 3.0 # seconds
    earthquake_current_intensity_g = 0.0
    liquefaction_is_active_for_physics = False # For building stiffness reduction
    liquefaction_threshold_g = 0.3 # PGA in g to trigger liquefaction
    LIQUEFACTION_SWAY_FREQUENCY_HZ = 0.5 # How fast the ground sways during liquefaction

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

            if not game_over_prompt_active and not destruction_animation_playing:
                # Handle UI events only if not waiting for restart choice
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
                    
                    if parameter_changed and not sample_building.is_destroyed: # Recalculate derived properties and mass
                        sample_building.total_height = sample_building.num_stories * sample_building.story_height
                        sample_building.aspect_ratio_l = sample_building.total_height / sample_building.footprint_length if sample_building.footprint_length > 0 else float('inf')
                        sample_building.aspect_ratio_w = sample_building.total_height / sample_building.footprint_width if sample_building.footprint_width > 0 else float('inf')
                        sample_building.calculated_mass = sample_building._calculate_total_mass() # Recalculate mass
                        if sample_building.calculated_mass <= 0: sample_building.calculated_mass = 1000 # Safety
                        sample_building.moment_of_inertia_kg_m2 = (1/3) * sample_building.calculated_mass * (sample_building.total_height**2) if sample_building.total_height > 0 else 1e6

                if event.type == pygame_gui.UI_BUTTON_PRESSED:
                    if event.ui_element == simulate_wind_button and not sample_building.is_destroyed:
                        wind_speed_mps = wind_speed_slider.get_current_value()
                        print(f"Simulating wind at {wind_speed_mps:.1f} m/s")
                        exposed_area = sample_building.total_height * sample_building.footprint_length 
                        wind_force_newtons = 0.5 * settings.AIR_DENSITY * (wind_speed_mps**2) * exposed_area * settings.DEFAULT_DRAG_COEFFICIENT
                        sample_building.apply_horizontal_force(wind_force_newtons, sample_building.total_height / 2)
                    
                    elif event.ui_element == simulate_earthquake_button and not sample_building.is_destroyed:
                        if not earthquake_active: # Prevent re-triggering if already active
                            earthquake_current_intensity_g = earthquake_intensity_slider.get_current_value()
                            print(f"Simulating earthquake with PGA: {earthquake_current_intensity_g:.2f}g")
                            earthquake_active = True
                            earthquake_timer = 0.0
                            if earthquake_current_intensity_g >= liquefaction_threshold_g:
                                print("Liquefaction triggered!")
                                liquefaction_is_active_for_physics = True
                                sample_building.set_stiffness_reduction_for_liquefaction(True) # Reduce building stiffness
                        else:
                            print("Earthquake already in progress.")

            
            # Handle confirmation dialog events
            if event.type == pygame_gui.UI_CONFIRMATION_DIALOG_CONFIRMED:
                if event.ui_element == confirmation_dialog:
                    print("Restarting simulation...")
                    sample_building = create_new_building() # Reset building
                    liquefaction_is_active_for_physics = False # Ensure liquefaction physics off on restart
                    game_over_prompt_active = False
                    confirmation_dialog = None # Clear the reference
            
            if event.type == pygame.USEREVENT: # pygame_gui uses USEREVENT for various things
                if event.user_type == pygame_gui.UI_WINDOW_CLOSE: # Check if it's our confirmation dialog
                     if event.ui_element == confirmation_dialog:
                        print("Exiting after destruction.")
                        liquefaction_is_active_for_physics = False # Ensure liquefaction physics off on exit
                        running = False # Or just keep game_over_prompt_active = True
                        game_over_prompt_active = False # Allow exit
                        confirmation_dialog = None


        # --- Game Logic Updates (conditionally) ---
        if not game_over_prompt_active and not destruction_animation_playing:
            # Update Clouds
            for cloud in clouds:
                cloud.rect.x += cloud.speed
                if cloud.speed > 0 and cloud.rect.left > settings.SCREEN_WIDTH:
                    cloud.rect.right = 0
                    cloud.rect.y = random.randint(20, settings.SCREEN_HEIGHT // 3)
                elif cloud.speed < 0 and cloud.rect.right < 0:
                    cloud.rect.left = settings.SCREEN_WIDTH
                    cloud.rect.y = random.randint(20, settings.SCREEN_HEIGHT // 3)
            # Update Building Physics
            sample_building.update_physics(time_delta)

            current_liquefaction_effect_scale = 0.0
            # Apply earthquake forces if active
            if earthquake_active:
                earthquake_timer += time_delta
                if earthquake_timer <= earthquake_duration:
                    # Simple sinusoidal ground acceleration
                    # Frequency of shaking (e.g., 2 Hz)
                    shake_frequency_hz = 2.0
                    ground_acceleration_mps2 = earthquake_current_intensity_g * 9.81 * math.sin(2 * math.pi * shake_frequency_hz * earthquake_timer)
                    
                    # Inertial force acts at CM (approx total_height / 2)
                    inertial_force = -sample_building.calculated_mass * ground_acceleration_mps2
                    sample_building.apply_horizontal_force(inertial_force, sample_building.total_height / 2)

                    if liquefaction_is_active_for_physics: # Animate ground only if liquefaction is active
                        # Scale oscillates between 0 and 1 for the visual effect
                        current_liquefaction_effect_scale = (math.sin(2 * math.pi * LIQUEFACTION_SWAY_FREQUENCY_HZ * earthquake_timer) + 1.0) / 2.0
                else:
                    earthquake_active = False
                    if liquefaction_is_active_for_physics:
                        sample_building.set_stiffness_reduction_for_liquefaction(False) # Restore stiffness
                        liquefaction_is_active_for_physics = False
                    print("Earthquake finished.")

            # Check for destruction and show prompt
            if sample_building.is_destroyed and not destruction_animation_playing:
                print("Building destruction triggered! Starting animation.")
                destruction_animation_playing = True
                # Generate fragments using the building's method
                destruction_animation_timer = 0.0 # Reset timer
                base_x_m = building_base_screen_x_center / settings.METERS_TO_PIXELS
                ground_y_pixels_at_base = biome_generator.get_ground_y_at_x(building_base_screen_x_center, current_biome, current_liquefaction_effect_scale) # Use current scale for fragment generation
                building_base_y_m = ground_y_pixels_at_base / settings.METERS_TO_PIXELS
                active_fragments = sample_building.generate_fragments(base_x_m, building_base_y_m, sample_building.angular_displacement_rad)
        
        if destruction_animation_playing:
            # Update fragments
            destruction_animation_timer += time_delta
            all_settled = True
            for fragment in active_fragments:
                fragment.update(time_delta, biome_generator.get_ground_y_at_x, current_biome)
                if not fragment.is_settled: # Note: fragment.update doesn't currently take liquefaction_effect_scale for its ground check. Could be added.
                    all_settled = False
            
            # End animation if all fragments settled OR timer exceeds 5 seconds
            if (all_settled and active_fragments) or destruction_animation_timer > 5.0:
                print(f"Destruction animation ended. Reason: {'All settled' if all_settled else 'Timer expired'}.")
                destruction_animation_playing = False
                game_over_prompt_active = True 
                if not confirmation_dialog: # Ensure dialog is not already up
                    confirmation_dialog = pygame_gui.windows.UIConfirmationDialog(
                        rect=pygame.Rect((settings.SCREEN_WIDTH // 2 - 150, settings.SCREEN_HEIGHT // 2 - 100), (300, 200)),
                        manager=ui_manager,
                        window_title="Building Destroyed!",
                        action_long_desc="The building has collapsed. Would you like to restart?",
                        action_short_name="Restart",
                        blocking=True 
                    )

        ui_manager.update(time_delta)

        # --- Rendering ---
        renderer.render_world(current_biome, sample_building, building_base_screen_x_center, clouds, active_fragments, destruction_animation_playing, liquefaction_effect_scale=current_liquefaction_effect_scale)
        ui_manager.draw_ui(screen) # Draw pygame_gui elements

        pygame.display.flip()

    pygame.quit()

if __name__ == "__main__":
    main()
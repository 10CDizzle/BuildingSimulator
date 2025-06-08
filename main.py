import pygame
import random
from config import settings
from graphics.renderer import Renderer, Cloud # Import Cloud
from core.biome_generator import BiomeGenerator
from core.building_structure import Building, CONCRETE # Import Building and an example material
from ui.gui_manager import GUIManager # Import GUIManager


def main():
    pygame.init()

    screen = pygame.display.set_mode((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    pygame.display.set_caption("2D Building Simulator")
    clock = pygame.time.Clock()

    # Instantiate BiomeGenerator
    biome_generator = BiomeGenerator(settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT)
    # Pass biome_generator to Renderer
    renderer = Renderer(screen, biome_generator)

    # --- UI Manager ---
    gui_manager = GUIManager()
    ui_margin = 20
    scrollbar_height = 20
    scrollbar_width = 200
    # Add scrollbars for building parameters
    # (param_name must match an attribute in the Building class)
    gui_manager.add_scrollbar(ui_margin, settings.SCREEN_HEIGHT - scrollbar_height * 5 - ui_margin, scrollbar_width, scrollbar_height, 1, 20, 5, "Stories", "num_stories")
    gui_manager.add_scrollbar(ui_margin, settings.SCREEN_HEIGHT - scrollbar_height * 4 - ui_margin, scrollbar_width, scrollbar_height, 2.0, 5.0, 3.0, "Story H (m)", "story_height")
    gui_manager.add_scrollbar(ui_margin, settings.SCREEN_HEIGHT - scrollbar_height * 3 - ui_margin, scrollbar_width, scrollbar_height, 5.0, 50.0, 15.0, "Length (m)", "footprint_length")
    gui_manager.add_scrollbar(ui_margin, settings.SCREEN_HEIGHT - scrollbar_height * 2 - ui_margin, scrollbar_width, scrollbar_height, 5.0, 50.0, 10.0, "Width (m)", "footprint_width")

    # --- Create a sample building ---
    sample_building = Building(
        num_stories=5,
        story_height=3.0,
        footprint_length=15.0, # meters
        footprint_width=10.0,  # meters
        primary_material=CONCRETE
    )
    building_screen_x_position = settings.SCREEN_WIDTH // 2 # Place it in the center

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
        event_list = pygame.event.get()
        # --- Event Handling ---
        for event in event_list:
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
        
        gui_manager.handle_events(event_list)

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

        # Update building parameters from UI
        gui_manager.update_building_from_ui(sample_building)


        # --- Rendering ---
        renderer.render_world(current_biome, sample_building, building_screen_x_position, clouds)
        gui_manager.draw_ui(screen) # Draw UI elements on top
        pygame.display.flip()

        # --- Cap FPS ---
        clock.tick(settings.FPS)

    pygame.quit()

if __name__ == "__main__":
    main()
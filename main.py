import pygame
from config import settings
from graphics.renderer import Renderer
from core.biome_generator import BiomeGenerator # Import BiomeGenerator


def main():
    pygame.init()

    screen = pygame.display.set_mode((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    pygame.display.set_caption("2D Building Simulator")
    clock = pygame.time.Clock()

    # Instantiate BiomeGenerator
    biome_generator = BiomeGenerator(settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT)
    # Pass biome_generator to Renderer
    renderer = Renderer(screen, biome_generator)
    # --- Game State ---
    # You can change this to test different biomes
    current_biome = "Dfc" # Example: Hot Desert
    # current_biome = "Af"  # Example: Tropical Rainforest
    # current_biome = "ET"  # Example: Tundra

    running = True
    while running:
        # --- Event Handling ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

        # --- Game Logic ---
        # (No complex logic yet)

        # --- Rendering ---
        renderer.render_world(current_biome)
        pygame.display.flip()

        # --- Cap FPS ---
        clock.tick(settings.FPS)

    pygame.quit()

if __name__ == "__main__":
    main()
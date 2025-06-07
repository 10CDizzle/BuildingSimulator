import pygame
from config import settings
from graphics.renderer import Renderer

def main():
    pygame.init()

    screen = pygame.display.set_mode((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    pygame.display.set_caption("2D Building Simulator")
    clock = pygame.time.Clock()

    renderer = Renderer(screen)

    # --- Game State ---
    # You can change this to test different biomes
    current_biome = "BWh" # Example: Hot Desert
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
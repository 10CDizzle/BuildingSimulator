import pygame
from config import settings

class Renderer:
    def __init__(self, screen):
        """
        Initializes the Renderer.
        :param screen: The Pygame screen surface to draw on.
        """
        self.screen = screen

    def render_world(self, current_biome_code="Af"):
        """
        Renders the game world based on the current biome.
        For a side view, this means a sky and a ground.
        :param current_biome_code: The Koppen code for the biome to render.
        """
        biome_colors = settings.BIOMES.get(current_biome_code)
        if not biome_colors:
            print(f"Warning: Biome code '{current_biome_code}' not found. Defaulting to Af.")
            biome_colors = settings.BIOMES["Af"]

        self.screen.fill(biome_colors["sky"])
        ground_rect = pygame.Rect(0, settings.SCREEN_HEIGHT * 2 // 3, settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT // 3)
        pygame.draw.rect(self.screen, biome_colors["ground"], ground_rect)
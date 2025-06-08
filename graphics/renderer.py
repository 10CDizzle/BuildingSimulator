import pygame
# from config import settings # settings.BIOMES is no longer used here

class Renderer:
    def __init__(self, screen, biome_generator):
        """
        Initializes the Renderer.
        :param screen: The Pygame screen surface to draw on.
        :param biome_generator: An instance of BiomeGenerator.
        """
        self.screen = screen
        self.biome_generator = biome_generator

    def render_world(self, current_biome_code="Af"):
        """
        Renders the game world based on the current biome.
        For a side view, this means a sky and a curvy ground.
        :param current_biome_code: The Koppen code for the biome to render.
        """
        biome_props = self.biome_generator.get_biome_properties(current_biome_code)
        sky_color = biome_props["sky"]
        ground_color = biome_props["ground"]

        self.screen.fill(sky_color)

        ground_points = self.biome_generator.generate_ground_points(current_biome_code)
        pygame.draw.polygon(self.screen, ground_color, ground_points)
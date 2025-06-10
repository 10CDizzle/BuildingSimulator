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

class Renderer:
    def __init__(self, screen, biome_generator):
        """
        Initializes the Renderer.
        :param screen: The Pygame screen surface to draw on.
        :param biome_generator: An instance of BiomeGenerator.
        """
        self.screen = screen
        self.biome_generator = biome_generator

    def render_world(self, current_biome_code="Af", building_to_draw=None, building_x_position=None, clouds=None):
        """
        Renders the game world based on the current biome.
        For a side view, this means a sky and a curvy ground.
        :param current_biome_code: The Koppen code for the biome to render.
        :param building_to_draw: Optional Building object to render.
        :param building_x_position: Optional x-coordinate for the center of the building.
        :param clouds: Optional list of Cloud objects to render.
        """
        biome_props = self.biome_generator.get_biome_properties(current_biome_code)
        sky_color = biome_props["sky"]
        ground_color = biome_props["ground"]

        self.screen.fill(sky_color)

        ground_points = self.biome_generator.generate_ground_points(current_biome_code)
        pygame.draw.polygon(self.screen, ground_color, ground_points)
        
        if clouds:
            self.render_clouds(clouds)

        if building_to_draw and building_x_position is not None:
            self.render_building(building_to_draw, building_x_position, current_biome_code)

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

    def render_building(self, building, x_center_screen, biome_code):
        """
        Renders a single building.
        :param building: The Building object to render.
        :param x_center_screen: The screen x-coordinate for the center of the building.
        :param biome_code: The current biome code to determine ground height.
        """
        # Building dimensions in pixels
        building_width_pixels = building.footprint_length * settings.METERS_TO_PIXELS
        building_height_pixels = building.total_height * settings.METERS_TO_PIXELS
        story_height_pixels = building.story_height * settings.METERS_TO_PIXELS

        # Determine building's left and right x-coordinates
        building_x_left = x_center_screen - building_width_pixels / 2
        building_x_right = x_center_screen + building_width_pixels / 2

        # Get ground y-coordinates at the left and right edges of the building
        ground_y_left = self.biome_generator.get_ground_y_at_x(building_x_left, biome_code)
        ground_y_right = self.biome_generator.get_ground_y_at_x(building_x_right, biome_code)

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
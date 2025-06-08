import math
import numpy as np # Though not used in this version, it's good to keep if you plan more complex terrain.
from config import settings

# Biome definitions (Koppen-inspired)
# Includes parameters for terrain generation:
# "sky": (R,G,B) color for the sky
# "ground": (R,G,B) color for the ground
# "amplitude": Max height variation of the terrain.
# "frequency": How many hills/valleys across the screen.
# "base_height_factor": Multiplier for SCREEN_HEIGHT to set the average ground level.
# "phase_shift": A small offset for the sine wave to vary terrain start.
BIOME_DATA = {
    "Af": { # Tropical rainforest
        "sky": settings.SKY_BLUE,
        "ground": settings.DARK_GREEN,
        "amplitude": 40,
        "frequency": 0.005,
        "base_height_factor": 2/3,
        "phase_shift": 1.0
    },
    "BWh": { # Hot desert
        "sky": (210, 220, 240), # Pale, hazy blue
        "ground": settings.SAND_YELLOW,
        "amplitude": 25,
        "frequency": 0.003,
        "base_height_factor": 0.7, # Slightly lower base for dunes
        "phase_shift": 0.5
    },
    "ET": { # Tundra
        "sky": (160, 170, 180), # Overcast grey
        "ground": (101, 67, 33), # Brownish
        "amplitude": 15,
        "frequency": 0.002,
        "base_height_factor": 3/4, # Higher, flatter terrain
        "phase_shift": 2.0
    },
    "Cfa": { # Humid subtropical (e.g., Southeastern US)
        "sky": (173, 216, 230), # Light blue
        "ground": (34, 139, 34), # Forest green
        "amplitude": 30,
        "frequency": 0.004,
        "base_height_factor": 0.68,
        "phase_shift": 1.5
    },
    "Dfc": { # Subarctic (e.g., Taiga)
        "sky": (176, 196, 222), # Steel blue
        "ground": (85, 107, 47), # Dark olive green
        "amplitude": 50,
        "frequency": 0.006,
        "base_height_factor": 0.75,
        "phase_shift": 0.0
    }
    # Add more Koppen classifications here
}

DEFAULT_BIOME_CODE = "Af" # Default if a code is not found

class BiomeGenerator:
    def __init__(self, screen_width, screen_height):
        """
        Initializes the BiomeGenerator.
        :param screen_width: Width of the game screen.
        :param screen_height: Height of the game screen.
        """
        self.screen_width = screen_width
        self.screen_height = screen_height

    def get_biome_properties(self, biome_code):
        """
        Retrieves the properties for a given biome code.
        If the code is not found, it returns properties for the DEFAULT_BIOME_CODE.
        :param biome_code: The Koppen code string for the desired biome.
        :return: A dictionary of biome properties.
        """
        if biome_code not in BIOME_DATA:
            print(f"Warning: Biome code '{biome_code}' not found. Using default biome '{DEFAULT_BIOME_CODE}'.")
            return BIOME_DATA[DEFAULT_BIOME_CODE]
        return BIOME_DATA[biome_code]

    def generate_ground_points(self, biome_code, num_points=None):
        """
        Generates a list of (x, y) points for a curvy ground polygon.
        The number of points can be specified, or defaults to screen_width / 10 for reasonable detail.
        :param biome_code: The Koppen code for the biome.
        :param num_points: The number of points to generate for the top edge of the terrain.
        :return: A list of (x,y) tuples representing the vertices of the ground polygon.
        """
        props = self.get_biome_properties(biome_code)
        base_ground_y = self.screen_height * props["base_height_factor"]
        amplitude = props["amplitude"]
        frequency = props["frequency"]
        phase_shift = props.get("phase_shift", 0.0) # Use .get for backward compatibility if not all biomes have it

        if num_points is None:
            num_points = max(50, int(self.screen_width / 10)) # Ensure at least 50 points, or one every 10 pixels

        points = []
        for i in range(num_points + 1):
            x = (self.screen_width / num_points) * i
            # Sine wave for simple curviness.
            y_offset = amplitude * math.sin(frequency * x + phase_shift)
            y = base_ground_y + y_offset
            points.append((x, min(self.screen_height -1, max(0, y)))) # Clamp y to be within screen bounds

        # Add points to close the polygon at the bottom of the screen
        points.append((self.screen_width, self.screen_height))
        points.append((0, self.screen_height))
        return points

    def get_available_biomes(self):
        """
        Returns a list of available biome codes.
        """
        return list(BIOME_DATA.keys())

    def get_ground_y_at_x(self, x_coord, biome_code):
        """
        Calculates the y-coordinate of the ground at a specific x-coordinate
        based on the biome's terrain generation parameters.
        :param x_coord: The x-coordinate on the screen.
        :param biome_code: The Koppen code for the biome.
        :return: The y-coordinate of the ground.
        """
        props = self.get_biome_properties(biome_code)
        base_ground_y = self.screen_height * props["base_height_factor"]
        amplitude = props["amplitude"]
        frequency = props["frequency"]
        phase_shift = props.get("phase_shift", 0.0)

        y_offset = amplitude * math.sin(frequency * x_coord + phase_shift)
        return min(self.screen_height -1, max(0, base_ground_y + y_offset))

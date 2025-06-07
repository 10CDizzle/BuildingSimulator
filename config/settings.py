# Screen dimensions
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
SKY_BLUE = (135, 206, 235)
LIGHT_GREEN = (144, 238, 144)
SAND_YELLOW = (244, 164, 96)
DARK_GREEN = (0, 100, 0)
GRAY = (128, 128, 128)

# Biome definitions (Koppen-inspired)
# For a side view, we'll define a sky color and a ground color.
# Format: "BIOME_CODE": {"sky": (R,G,B), "ground": (R,G,B)}
BIOMES = {
    "Af": { # Tropical rainforest
        "sky": SKY_BLUE,
        "ground": DARK_GREEN
    },
    "BWh": { # Hot desert
        "sky": (210, 220, 240), # Pale, hazy blue
        "ground": SAND_YELLOW
    },
    "ET": { # Tundra
        "sky": (160, 170, 180), # Overcast grey
        "ground": (101, 67, 33) # Brownish
    }
    # Add more Koppen classifications here
}
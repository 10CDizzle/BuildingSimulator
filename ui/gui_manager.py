import pygame
from config import settings

class Scrollbar:
    def __init__(self, x, y, width, height, min_val, max_val, current_val, label="", param_name=None):
        self.rect = pygame.Rect(x, y, width, height)
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.current_val = float(current_val)
        self.label = label
        self.param_name = param_name # To identify what building parameter this controls

        self.handle_width = 10
        self.handle_rect = pygame.Rect(0, 0, self.handle_width, height)
        self._update_handle_pos()

        self.dragging = False
        self.font = pygame.font.Font(None, 24)

    def _update_handle_pos(self):
        # Calculate handle position based on current_val
        val_range = self.max_val - self.min_val
        if val_range == 0:
            ratio = 0
        else:
            ratio = (self.current_val - self.min_val) / val_range
        self.handle_rect.centerx = self.rect.left + ratio * (self.rect.width - self.handle_width) + self.handle_width / 2
        self.handle_rect.centery = self.rect.centery

    def _update_value_from_mouse(self, mouse_x):
        # Calculate value based on mouse_x relative to the scrollbar
        relative_x = mouse_x - (self.rect.left + self.handle_width / 2)
        ratio = relative_x / (self.rect.width - self.handle_width)
        ratio = max(0, min(1, ratio)) # Clamp between 0 and 1

        val_range = self.max_val - self.min_val
        self.current_val = self.min_val + ratio * val_range
        # For integer parameters, we might want to round
        if self.param_name in ["num_stories"]: # Add other int params here
            self.current_val = round(self.current_val)
        self._update_handle_pos()

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1 and self.rect.collidepoint(event.pos):
                self.dragging = True
                self._update_value_from_mouse(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                self._update_value_from_mouse(event.pos[0])

    def draw(self, surface):
        # Draw track
        pygame.draw.rect(surface, settings.GRAY, self.rect)
        pygame.draw.rect(surface, settings.BLACK, self.rect, 1)
        # Draw handle
        pygame.draw.rect(surface, settings.DARK_GREEN, self.handle_rect)
        pygame.draw.rect(surface, settings.BLACK, self.handle_rect, 1)

        # Draw label and value
        if self.param_name in ["num_stories"]:
            text = f"{self.label}: {int(self.current_val)}"
        else:
            text = f"{self.label}: {self.current_val:.1f}"
        label_surface = self.font.render(text, True, settings.BLACK)
        surface.blit(label_surface, (self.rect.x, self.rect.y - 20))

    def get_value(self):
        if self.param_name in ["num_stories"]:
            return int(self.current_val)
        return self.current_val

class GUIManager:
    def __init__(self):
        self.elements = []

    def add_scrollbar(self, x, y, width, height, min_val, max_val, current_val, label, param_name):
        scrollbar = Scrollbar(x, y, width, height, min_val, max_val, current_val, label, param_name)
        self.elements.append(scrollbar)
        return scrollbar

    def handle_events(self, event_list):
        for element in self.elements:
            if hasattr(element, 'handle_event'):
                for event in event_list: # Pass individual events
                    element.handle_event(event)

    def update_building_from_ui(self, building):
        for element in self.elements:
            if isinstance(element, Scrollbar) and element.param_name:
                if hasattr(building, element.param_name):
                    setattr(building, element.param_name, element.get_value())
                # Special handling for derived properties if needed
                if element.param_name == "num_stories" or element.param_name == "story_height":
                    building.total_height = building.num_stories * building.story_height
                if element.param_name == "footprint_length" or element.param_name == "total_height":
                     building.aspect_ratio_l = building.total_height / building.footprint_length if building.footprint_length > 0 else float('inf')

    def draw_ui(self, surface):
        for element in self.elements:
            if hasattr(element, 'draw'):
                element.draw(surface)
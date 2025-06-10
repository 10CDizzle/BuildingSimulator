from enum import Enum, auto
import math
import random
from graphics.renderer import BuildingFragment


class Material:
    """Represents material properties for building components."""
    def __init__(self, name: str, elastic_modulus: float, density: float, damping_ratio: float, shear_strength: float):
        self.name = name
        self.elastic_modulus = elastic_modulus  # E, in Pascals (Pa)
        self.density = density                  # kg/m^3
        self.damping_ratio = damping_ratio      # Dimensionless
        self.shear_strength = shear_strength    # Pascals (Pa)

    def __str__(self):
        return self.name

# Example predefined materials - these could be loaded from a config file later
CONCRETE = Material(name="Concrete", elastic_modulus=30e9, density=2400, damping_ratio=0.05, shear_strength=2.5e6)
STEEL = Material(name="Steel", elastic_modulus=200e9, density=7850, damping_ratio=0.02, shear_strength=250e6)
WOOD = Material(name="Wood", elastic_modulus=10e9, density=600, damping_ratio=0.07, shear_strength=5e6)


class MassDistribution(Enum):
    UNIFORM = auto()
    CONCENTRATED_TOP = auto()
    # Add more as needed, e.g., CONCENTRATED_MID

class StructuralSystemType(Enum):
    FRAME_MOMENT_RESISTING = auto()
    FRAME_BRACED_CONCENTRIC = auto()
    FRAME_BRACED_ECCENTRIC = auto()
    SHEAR_WALLS = auto()
    CORE_WALL = auto()
    DIAGRID = auto()
    # ... more types

class FoundationType(Enum):
    SHALLOW_SPREAD_FOOTINGS = auto()
    SHALLOW_SLAB_ON_GRADE = auto()
    DEEP_PILES = auto()
    DEEP_CAISSONS = auto()
    BASE_ISOLATION = auto()
    # ... more types

class PlanSymmetry(Enum):
    SYMMETRIC = auto()
    ASYMMETRIC_SINGLE_AXIS = auto() # Simplified
    ASYMMETRIC_DUAL_AXIS = auto()   # Simplified

class DiaphragmRigidity(Enum):
    FLEXIBLE = auto()
    RIGID = auto()
    SEMI_RIGID = auto()

class JointType(Enum): # Simplified representation of connection quality/type
    RIGID = auto()
    PINNED = auto()
    SEMI_RIGID = auto()


class Building:
    """Represents a single building structure with its properties."""
    def __init__(self,
                 # Structural Parameters
                 num_stories: int = 3,
                 story_height: float = 3.0,  # meters
                 footprint_length: float = 10.0,  # meters (e.g., along x-axis)
                 footprint_width: float = 10.0,   # meters (e.g., along y-axis)
                 mass_distribution: MassDistribution = MassDistribution.UNIFORM,
                 primary_material: Material = CONCRETE,
                 structural_system: StructuralSystemType = StructuralSystemType.FRAME_MOMENT_RESISTING,
                 foundation_type: FoundationType = FoundationType.SHALLOW_SLAB_ON_GRADE,
                 # Dynamic Response Parameters (can be initial estimates or targets for procedural generation)
                 target_natural_period: float = None,  # seconds
                 overall_damping_ratio: float = None, # Overrides material's if set
                 # Geometric & Layout Features
                 plan_symmetry: PlanSymmetry = PlanSymmetry.SYMMETRIC,
                 has_soft_story: bool = False, # Simplified representation of openings/discontinuities
                 floor_diaphragm_rigidity: DiaphragmRigidity = DiaphragmRigidity.RIGID,
                 facade_cladding_mass_per_area: float = 75.0,  # kg/m^2, for facade weight
                 # Connection & Detailing Quality (simplified)
                 connection_quality: JointType = JointType.RIGID,
                 redundancy_level: float = 0.7,  # Normalized 0 (low) to 1 (high)
                 ductility_level: float = 0.6,   # Normalized 0 (low) to 1 (high)
                 # Optional Realism Enhancers
                 has_non_structural_components: bool = True, # e.g., partition walls, ceilings
                 retrofitting_measures: list = None, # List of strings or enums describing retrofits
                 # Rotational Physics properties
                 rotational_stiffness_nm_per_rad: float = 5e7, # Nm/rad, arbitrary
                 rotational_damping_nm_s_per_rad: float = 1e6,  # Nms/rad, arbitrary
                 max_safe_angular_displacement_rad: float = math.radians(20) # e.g., 20 degrees
                 ):

        # Structural Parameters
        self.num_stories = num_stories
        self.story_height = story_height
        self.total_height = num_stories * story_height

        self.footprint_length = footprint_length
        self.footprint_width = footprint_width
        self.aspect_ratio_l = self.total_height / self.footprint_length if self.footprint_length > 0 else float('inf')
        self.aspect_ratio_w = self.total_height / self.footprint_width if self.footprint_width > 0 else float('inf')

        self.mass_distribution = mass_distribution
        self.primary_material = primary_material
        self.structural_system = structural_system
        self.foundation_type = foundation_type

        # Dynamic Response Parameters
        self.target_natural_period = target_natural_period
        self.effective_damping_ratio = overall_damping_ratio if overall_damping_ratio is not None else primary_material.damping_ratio
        self.mode_shapes = []  # Placeholder for more advanced modal analysis [(period, participation_x, participation_y, participation_torsion), ...]

        # Geometric & Layout Features
        self.plan_symmetry = plan_symmetry
        self.has_soft_story = has_soft_story # Could be expanded to specify which story
        self.floor_diaphragm_rigidity = floor_diaphragm_rigidity
        self.facade_cladding_mass_per_area = facade_cladding_mass_per_area

        # Connection & Detailing Quality
        self.connection_quality = connection_quality
        self.redundancy_level = max(0.0, min(1.0, redundancy_level))
        self.ductility_level = max(0.0, min(1.0, ductility_level))

        # Optional Realism Enhancers
        self.has_non_structural_components = has_non_structural_components
        self.retrofitting_measures = retrofitting_measures if retrofitting_measures is not None else []

        # --- Physics State ---
        self.calculated_mass: float = self._calculate_total_mass()
        # Ensure mass is not zero to avoid division by zero errors
        if self.calculated_mass <= 0:
            self.calculated_mass = 1000 # Default small mass if calculation fails

        self.is_destroyed: bool = False

        self.angular_displacement_rad: float = 0.0       # Current sway angle
        self.angular_velocity_rad_per_s: float = 0.0     # Current angular velocity
        self.accumulated_torque_nm: float = 0.0          # Torque accumulated in a frame
        self.rotational_stiffness_nm_per_rad = rotational_stiffness_nm_per_rad
        self.rotational_damping_nm_s_per_rad = rotational_damping_nm_s_per_rad
        # Moment of inertia (approx. as thin rod rotating about base: 1/3 * m * h^2)
        self.moment_of_inertia_kg_m2: float = (1/3) * self.calculated_mass * (self.total_height**2) if self.total_height > 0 else 1e6
        self.max_safe_angular_displacement_rad = max_safe_angular_displacement_rad

        self.calculated_natural_period: float = self._calculate_natural_period()

    def _calculate_total_mass(self) -> float:
        # Placeholder: More detailed calculation needed based on geometry, materials, system
        structural_volume = self.footprint_length * self.footprint_width * self.total_height * 0.15 # Rough factor for structural elements
        mass = structural_volume * self.primary_material.density
        facade_area = 2 * (self.footprint_length + self.footprint_width) * self.total_height
        mass += facade_area * self.facade_cladding_mass_per_area
        # Add floor mass (simplified: assume floors are 10% of story volume and same density)
        floor_volume_per_story = self.footprint_length * self.footprint_width * self.story_height * 0.10
        mass += floor_volume_per_story * self.primary_material.density * self.num_stories

        return mass

    def _calculate_natural_period(self) -> float:
        # Placeholder: Use target if available, else very rough estimate.
        # E.g., T = 0.1 * N for steel, T = 0.075 * N for RC, or Ct * H^(3/4)
        if self.target_natural_period:
            return self.target_natural_period
        return 0.1 * self.num_stories # Very generic placeholder

    def __str__(self):
        return (f"Building: {self.num_stories} stories, {self.total_height:.1f}m H, "
                f"{self.footprint_length:.1f}x{self.footprint_width:.1f}m Base, "
                f"Mat: {self.primary_material}, Sys: {self.structural_system.name}")

    def apply_horizontal_force(self, force_x: float, application_height_m: float = None):
        """
        Applies a horizontal force at a certain height, converting it to torque.
        :param force_x: Force in the x-direction (Newtons).
        :param application_height_m: Height from the base where the force is applied (meters).
                                     Defaults to mid-height of the building.
        """
        if application_height_m is None:
            application_height_m = self.total_height / 2
        
        torque = force_x * application_height_m
        self.accumulated_torque_nm += torque

    def update_physics(self, delta_time: float):
        """
        Updates the building's angular displacement and velocity based on applied torques.
        Models as a rotational spring-damper system using Euler integration.
        :param delta_time: Time elapsed since the last update (seconds).
        """
        if self.is_destroyed or self.moment_of_inertia_kg_m2 <= 0:
            return # No physics updates if destroyed or invalid inertia

        restoring_torque = -self.rotational_stiffness_nm_per_rad * self.angular_displacement_rad
        damping_torque = -self.rotational_damping_nm_s_per_rad * self.angular_velocity_rad_per_s
        
        net_torque = self.accumulated_torque_nm + restoring_torque + damping_torque
        
        angular_acceleration = net_torque / self.moment_of_inertia_kg_m2
        self.angular_velocity_rad_per_s += angular_acceleration * delta_time
        self.angular_displacement_rad += self.angular_velocity_rad_per_s * delta_time
        self.accumulated_torque_nm = 0.0 # Reset torque for the next frame

        # Check for destruction
        if abs(self.angular_displacement_rad) > self.max_safe_angular_displacement_rad:
            self.is_destroyed = True
            self.angular_velocity_rad_per_s = 0 # Stop further motion
            self.angular_displacement_rad = math.copysign(self.max_safe_angular_displacement_rad, self.angular_displacement_rad) # Settle at max angle

    def generate_fragments(self, base_x_m, building_base_y_m, initial_lean_angle_rad):
        """
        Generates BuildingFragment objects when the building is destroyed.
        :param base_x_m: The x-coordinate of the building's base center in meters.
        :param building_base_y_m: The y-coordinate of the building's base in meters (ground level).
        :param initial_lean_angle_rad: The building's lean angle at collapse.
        :return: A list of BuildingFragment objects.
        """
        fragments = []
        num_fragments_per_story_width = 2 # How many pieces to break each story into horizontally
        fragment_width_m = self.footprint_length / num_fragments_per_story_width
        fragment_height_m = self.story_height

        # Color for fragments (could be based on material)
        gray_val = random.randint(100, 180) if hasattr(self.primary_material, 'color') else 120 # Placeholder
        fragment_color = (gray_val, gray_val, gray_val)

        for story_n in range(self.num_stories):
            story_bottom_y_m = building_base_y_m - ((story_n + 1) * self.story_height) # Y is screen coords
            story_top_y_m = building_base_y_m - (story_n * self.story_height)

            for i in range(num_fragments_per_story_width):
                frag_base_x_offset_m = (i - num_fragments_per_story_width / 2 + 0.5) * fragment_width_m
                
                # Initial center of the fragment before building lean
                center_x_m = base_x_m + frag_base_x_offset_m
                center_y_m = story_bottom_y_m + fragment_height_m / 2

                # Apply building's overall lean to the fragment's initial position (simplified)
                # Fragment's height from base for lean calculation
                height_from_base_for_lean = (story_n + 0.5) * self.story_height
                lean_dx_m = height_from_base_for_lean * math.tan(initial_lean_angle_rad)
                center_x_m += lean_dx_m

                # Define rectangle points for the fragment (in world meters, around its own center_x_m, center_y_m)
                hw, hh = fragment_width_m / 2, fragment_height_m / 2
                cx, cy = center_x_m, center_y_m

                # Max perturbation as a fraction of half-dimensions
                perturb_scale_w = 0.3 * hw
                perturb_scale_h = 0.3 * hh

                def r_offset(scale):
                    return random.uniform(-scale, scale)

                # Define 8 points for a jagged polygon, in order (e.g., clockwise)
                # Top-left, top-mid, top-right, right-mid, bottom-right, bottom-mid, bottom-left, left-mid
                points_m = [
                    (cx - hw + r_offset(perturb_scale_w), cy - hh + r_offset(perturb_scale_h)), # Top-left
                    (cx       + r_offset(perturb_scale_w), cy - hh + r_offset(perturb_scale_h)), # Top-mid
                    (cx + hw + r_offset(perturb_scale_w), cy - hh + r_offset(perturb_scale_h)), # Top-right
                    (cx + hw + r_offset(perturb_scale_w), cy       + r_offset(perturb_scale_h)), # Right-mid
                    (cx + hw + r_offset(perturb_scale_w), cy + hh + r_offset(perturb_scale_h)), # Bottom-right
                    (cx       + r_offset(perturb_scale_w), cy + hh + r_offset(perturb_scale_h)), # Bottom-mid
                    (cx - hw + r_offset(perturb_scale_w), cy + hh + r_offset(perturb_scale_h)), # Bottom-left
                    (cx - hw + r_offset(perturb_scale_w), cy       + r_offset(perturb_scale_h))  # Left-mid
                ]


                # Initial velocities - make them explode outwards and upwards a bit
                vel_x_mps = random.uniform(-4, 4) + (lean_dx_m * 0.3) # Add some lean influence, increased spread
                vel_y_mps = random.uniform(-5, 1) - (story_n * 0.5) # Higher stories get more upward kick
                angular_vel_rad_s = random.uniform(-math.pi/2, math.pi/2)

                fragments.append(BuildingFragment(points_m, fragment_color, vel_x_mps, vel_y_mps, angular_vel_rad_s))
        return fragments
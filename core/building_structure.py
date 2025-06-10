from enum import Enum, auto
import math

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
                 rotational_damping_nm_s_per_rad: float = 1e6  # Nms/rad, arbitrary
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

        self.angular_displacement_rad: float = 0.0       # Current sway angle
        self.angular_velocity_rad_per_s: float = 0.0     # Current angular velocity
        self.accumulated_torque_nm: float = 0.0          # Torque accumulated in a frame
        self.rotational_stiffness_nm_per_rad = rotational_stiffness_nm_per_rad
        self.rotational_damping_nm_s_per_rad = rotational_damping_nm_s_per_rad
        # Moment of inertia (approx. as thin rod rotating about base: 1/3 * m * h^2)
        self.moment_of_inertia_kg_m2: float = (1/3) * self.calculated_mass * (self.total_height**2) if self.total_height > 0 else 1e6

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
        if self.moment_of_inertia_kg_m2 <= 0: return # Safety check

        restoring_torque = -self.rotational_stiffness_nm_per_rad * self.angular_displacement_rad
        damping_torque = -self.rotational_damping_nm_s_per_rad * self.angular_velocity_rad_per_s
        
        net_torque = self.accumulated_torque_nm + restoring_torque + damping_torque
        
        angular_acceleration = net_torque / self.moment_of_inertia_kg_m2
        self.angular_velocity_rad_per_s += angular_acceleration * delta_time
        self.angular_displacement_rad += self.angular_velocity_rad_per_s * delta_time
        self.accumulated_torque_nm = 0.0 # Reset torque for the next frame
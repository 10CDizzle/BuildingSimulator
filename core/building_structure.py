from enum import Enum, auto
import math
import random

import numpy as np

from graphics.renderer import BuildingFragment
from core import physics


class Material:
    """Represents material properties for building components."""
    def __init__(self, name: str, elastic_modulus: float, density: float, damping_ratio: float,
                 shear_strength: float, allowable_axial_stress: float):
        self.name = name
        self.elastic_modulus = elastic_modulus  # E, in Pascals (Pa)
        self.density = density                  # kg/m^3
        self.damping_ratio = damping_ratio      # Dimensionless
        self.shear_strength = shear_strength    # Pascals (Pa)
        # Working/allowable axial compressive stress, used to size columns for the
        # gravity load they carry (Pa). Roughly service-level values.
        self.allowable_axial_stress = allowable_axial_stress

    def __str__(self):
        return self.name

# Example predefined materials - these could be loaded from a config file later
CONCRETE = Material(name="Concrete", elastic_modulus=30e9, density=2400, damping_ratio=0.05, shear_strength=2.5e6, allowable_axial_stress=12e6)
STEEL = Material(name="Steel", elastic_modulus=200e9, density=7850, damping_ratio=0.02, shear_strength=250e6, allowable_axial_stress=150e6)
WOOD = Material(name="Wood", elastic_modulus=10e9, density=600, damping_ratio=0.07, shear_strength=5e6, allowable_axial_stress=8e6)


class MassDistribution(Enum):
    UNIFORM = auto()
    CONCENTRATED_TOP = auto()

class StructuralSystemType(Enum):
    FRAME_MOMENT_RESISTING = auto()
    FRAME_BRACED_CONCENTRIC = auto()
    FRAME_BRACED_ECCENTRIC = auto()
    SHEAR_WALLS = auto()
    CORE_WALL = auto()
    DIAGRID = auto()

class FoundationType(Enum):
    SHALLOW_SPREAD_FOOTINGS = auto()
    SHALLOW_SLAB_ON_GRADE = auto()
    DEEP_PILES = auto()
    DEEP_CAISSONS = auto()
    BASE_ISOLATION = auto()

class PlanSymmetry(Enum):
    SYMMETRIC = auto()
    ASYMMETRIC_SINGLE_AXIS = auto()
    ASYMMETRIC_DUAL_AXIS = auto()

class DiaphragmRigidity(Enum):
    FLEXIBLE = auto()
    RIGID = auto()
    SEMI_RIGID = auto()

class JointType(Enum):
    RIGID = auto()
    PINNED = auto()
    SEMI_RIGID = auto()


class Building:
    """A building modelled as a multi-degree-of-freedom dynamic system.

    The lateral response is a shear+flexural stack on a flexible foundation
    (soil-structure interaction), integrated in time with Newmark-beta and driven
    by wind / earthquake / flood load vectors. Failure is governed by inter-story
    drift through a progressive-collapse model. All the mechanics live in
    :mod:`core.physics`; this class owns the building's parameters, the assembled
    system, and the evolving dynamic state.
    """

    def __init__(self,
                 num_stories: int = 5,
                 story_height: float = 3.0,
                 footprint_length: float = 15.0,
                 footprint_width: float = 10.0,
                 primary_material: Material = CONCRETE,
                 structural_system: StructuralSystemType = StructuralSystemType.FRAME_MOMENT_RESISTING,
                 mass_distribution: MassDistribution = MassDistribution.UNIFORM,
                 foundation_type: FoundationType = FoundationType.SHALLOW_SLAB_ON_GRADE,
                 soil_profile: physics.SoilProfile = None,
                 ductility_level: float = 0.6,
                 redundancy_level: float = 0.7,
                 facade_cladding_mass_per_area: float = 75.0,
                 overall_damping_ratio: float = None,
                 plan_symmetry: PlanSymmetry = PlanSymmetry.SYMMETRIC,
                 time_step: float = 1.0 / 60.0):

        self.num_stories = num_stories
        self.story_height = story_height
        self.footprint_length = footprint_length
        self.footprint_width = footprint_width
        self.primary_material = primary_material
        self.structural_system = structural_system
        self.mass_distribution = mass_distribution
        self.foundation_type = foundation_type
        self.soil_profile = soil_profile if soil_profile is not None else physics.FIRM_SOIL
        self.ductility_level = max(0.0, min(1.0, ductility_level))
        self.redundancy_level = max(0.0, min(1.0, redundancy_level))
        self.facade_cladding_mass_per_area = facade_cladding_mass_per_area
        self.plan_symmetry = plan_symmetry
        self.effective_damping_ratio = (overall_damping_ratio if overall_damping_ratio is not None
                                        else primary_material.damping_ratio)
        self.dt = time_step

        self.recompute_derived_properties()
        self.build_model()

    # -- Geometry / mass -----------------------------------------------------

    def recompute_derived_properties(self):
        """Recompute quantities derived from the structural parameters."""
        self.total_height = self.num_stories * self.story_height
        self.aspect_ratio_l = self.total_height / self.footprint_length if self.footprint_length > 0 else float('inf')
        self.aspect_ratio_w = self.total_height / self.footprint_width if self.footprint_width > 0 else float('inf')

    # -- Dynamic model assembly ---------------------------------------------

    def build_model(self):
        """Assemble the SSI system, integrator, and collapse model; reset state.

        Call after any change to geometry, material, structural system, or soil.
        """
        self.recompute_derived_properties()

        self.M, self.C, self.K, self.influence = physics.build_ssi_system(self, self.soil_profile)
        self.ndof = self.M.shape[0]
        self.n = self.num_stories
        self.height_of_floor = physics.floor_heights(self)            # m above base
        self.calculated_mass = float(physics.floor_masses(self).sum())

        modal = physics.modal_analysis(self.M, self.K)
        self.fundamental_period = float(modal.periods[0])

        self.collapse = physics.ProgressiveCollapse(self)
        self.drift_capacity = self.collapse.capacity
        self.integrator = physics.NewmarkIntegrator(self.M, self.C, self.K, self.dt)

        self.q = np.zeros(self.ndof)     # displacements [v_1..v_N, u_f, theta_f]
        self.qd = np.zeros(self.ndof)    # velocities
        self.qdd = np.zeros(self.ndof)   # accelerations
        self.is_destroyed = False

    def set_soil_profile(self, soil_profile):
        """Swap the soil (e.g. liquefaction) and refactorise in place.

        Keeps the current dynamic state; only the foundation springs/dashpots and
        the integrator's effective stiffness change.
        """
        self.soil_profile = soil_profile
        k_h, k_r = physics.soil_stiffness(self, soil_profile)
        c_h, c_r = physics.soil_damping(self, soil_profile)
        n = self.n
        self.K[n, n] = k_h
        self.K[n + 1, n + 1] = k_r
        self.C[n, n] = c_h
        self.C[n + 1, n + 1] = c_r
        self.integrator.update_system(K=self.K, C=self.C)

    # -- Time stepping -------------------------------------------------------

    def update_physics(self, delta_time=None, ground_acceleration=0.0,
                       wind_force=None, flood_force=None):
        """Advance the dynamic state one step under the given loads.

        ``ground_acceleration`` is the base input (m/s^2); ``wind_force`` and
        ``flood_force`` are per-floor horizontal force vectors (length N) or None.
        The fixed model time step is used so the integrator stays factorised.
        """
        if self.is_destroyed:
            return

        load = physics.seismic_force(self.M, self.influence, ground_acceleration)
        floor_load = None
        if wind_force is not None:
            floor_load = np.asarray(wind_force, dtype=float)
        if flood_force is not None:
            flood = np.asarray(flood_force, dtype=float)
            floor_load = flood if floor_load is None else floor_load + flood
        if floor_load is not None:
            load = load + physics.structural_force_to_ssi(floor_load, self.height_of_floor)

        self.q, self.qd, self.qdd = self.integrator.step(self.q, self.qd, self.qdd, load)

        if self.collapse.update(self.q[:self.n]):
            self.K[:self.n, :self.n] = self.collapse.stiffness_matrix()
            self.integrator.update_system(K=self.K)
        if self.collapse.is_collapsed:
            self.is_destroyed = True

    # -- Response readouts (for rendering & UI) -----------------------------

    def floor_displacements(self):
        """Absolute lateral displacement of each floor relative to ground (m).

        ``x_i = u_f + theta_f * z_i + v_i`` -- foundation sway, rocking, and
        structural distortion combined.
        """
        v = self.q[:self.n]
        u_f = self.q[self.n]
        theta_f = self.q[self.n + 1]
        return u_f + theta_f * self.height_of_floor + v

    @property
    def base_sway(self):
        """Foundation horizontal displacement (m)."""
        return float(self.q[self.n])

    @property
    def current_drift_ratios(self):
        return physics.story_drifts(self.q[:self.n], self.story_height)

    @property
    def max_drift_ratio(self):
        return float(np.max(np.abs(self.current_drift_ratios))) if self.n else 0.0

    @property
    def num_failed_stories(self):
        return int(np.count_nonzero(self.collapse.failed))

    @property
    def angular_displacement_rad(self):
        """Roof lean angle, kept for fragment generation at collapse."""
        if self.total_height <= 0:
            return 0.0
        return math.atan2(float(self.floor_displacements()[-1]), self.total_height)

    def __str__(self):
        return (f"Building: {self.num_stories} stories, {self.total_height:.1f}m H, "
                f"{self.footprint_length:.1f}x{self.footprint_width:.1f}m Base, "
                f"Mat: {self.primary_material}, Sys: {self.structural_system.name}, "
                f"T1={self.fundamental_period:.2f}s")

    # -- Destruction --------------------------------------------------------

    def generate_fragments(self, base_x_m, building_base_y_m, initial_lean_angle_rad):
        """Generate BuildingFragment objects when the building collapses."""
        fragments = []
        num_fragments_per_story_width = 2
        fragment_width_m = self.footprint_length / num_fragments_per_story_width
        fragment_height_m = self.story_height

        gray_val = 120
        fragment_color = (gray_val, gray_val, gray_val)

        for story_n in range(self.num_stories):
            story_bottom_y_m = building_base_y_m - ((story_n + 1) * self.story_height)

            for i in range(num_fragments_per_story_width):
                frag_base_x_offset_m = (i - num_fragments_per_story_width / 2 + 0.5) * fragment_width_m
                center_x_m = base_x_m + frag_base_x_offset_m
                center_y_m = story_bottom_y_m + fragment_height_m / 2

                height_from_base_for_lean = (story_n + 0.5) * self.story_height
                lean_dx_m = height_from_base_for_lean * math.tan(initial_lean_angle_rad)
                center_x_m += lean_dx_m

                hw, hh = fragment_width_m / 2, fragment_height_m / 2
                cx, cy = center_x_m, center_y_m
                perturb_scale_w = 0.3 * hw
                perturb_scale_h = 0.3 * hh

                def r_offset(scale):
                    return random.uniform(-scale, scale)

                points_m = [
                    (cx - hw + r_offset(perturb_scale_w), cy - hh + r_offset(perturb_scale_h)),
                    (cx + r_offset(perturb_scale_w), cy - hh + r_offset(perturb_scale_h)),
                    (cx + hw + r_offset(perturb_scale_w), cy - hh + r_offset(perturb_scale_h)),
                    (cx + hw + r_offset(perturb_scale_w), cy + r_offset(perturb_scale_h)),
                    (cx + hw + r_offset(perturb_scale_w), cy + hh + r_offset(perturb_scale_h)),
                    (cx + r_offset(perturb_scale_w), cy + hh + r_offset(perturb_scale_h)),
                    (cx - hw + r_offset(perturb_scale_w), cy + hh + r_offset(perturb_scale_h)),
                    (cx - hw + r_offset(perturb_scale_w), cy + r_offset(perturb_scale_h)),
                ]

                vel_x_mps = random.uniform(-4, 4) + (lean_dx_m * 0.3)
                vel_y_mps = random.uniform(-5, 1) - (story_n * 0.5)
                angular_vel_rad_s = random.uniform(-math.pi / 2, math.pi / 2)

                fragments.append(BuildingFragment(points_m, fragment_color, vel_x_mps, vel_y_mps, angular_vel_rad_s))
        return fragments

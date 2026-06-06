"""Multi-degree-of-freedom structural dynamics for the building simulator.

This module is the physics core of the simulation. It is deliberately free of
any pygame / rendering dependency so it can be unit-tested in isolation and
reasoned about as pure mechanics. Everything here is SI: metres, kilograms,
seconds, newtons, pascals.

The building is idealised as a *shear building*: each floor is a lumped mass
connected to the floor below by a lateral stiffness, giving one horizontal
degree of freedom per floor. The equation of motion is

    M u'' + C u' + K u = F(t)

where ``u`` is the vector of floor displacements relative to the ground.

Build status (see the improvement roadmap): this file is being grown one
milestone at a time, each backed by tests in ``tests/test_physics.py``.

  * Step 1 (this commit): section sizing, lumped floor masses, and the shear
    stiffness matrix, plus the pure linear-algebra assembly helpers.

Later steps add flexural behaviour, modal analysis, Rayleigh damping, the
Newmark-beta integrator, soil-structure interaction, loads, and progressive
collapse.
"""

import numpy as np

# --- Physical constants -----------------------------------------------------

GRAVITY = 9.81  # m/s^2

# --- Design heuristics (sensible defaults; may be exposed later) -------------

DEFAULT_BAY_SPACING_M = 6.0      # typical column grid spacing
DEFAULT_SLAB_THICKNESS_M = 0.15  # equivalent solid floor-slab thickness
DEFAULT_LIVE_LOAD_KG_PER_M2 = 200.0  # ~2 kPa service live load mass allowance
MIN_COLUMN_AREA_M2 = 0.09        # 300 mm x 300 mm minimum practical column


# ---------------------------------------------------------------------------
# Section / structural property derivation
# ---------------------------------------------------------------------------

def estimate_column_count(footprint_length, footprint_width, bay_spacing=DEFAULT_BAY_SPACING_M):
    """Number of vertical columns on a regular bay grid covering the footprint.

    A building ``footprint_length`` x ``footprint_width`` metres is gridded into
    bays roughly ``bay_spacing`` metres apart, giving ``(nx) x (ny)`` columns at
    the grid intersections. A minimum 2x2 grid is enforced so every building has
    corner columns.
    """
    nx = max(2, int(round(footprint_length / bay_spacing)) + 1)
    ny = max(2, int(round(footprint_width / bay_spacing)) + 1)
    return nx * ny


def column_section(building):
    """Size a representative square column from the gravity load it carries.

    The total building weight is shared across all columns; each column is sized
    so its base axial stress equals the material's allowable axial stress (with a
    practical minimum size). Returns ``(area_m2, second_moment_of_area_m4)`` for a
    square section, where ``I = b**4 / 12``.

    Sizing columns from real gravity demand is what makes taller / heavier
    buildings end up with stiffer columns, so the natural period grows with
    height the way it does in reality rather than via a tuned constant.
    """
    masses = floor_masses(building)
    total_weight_n = float(np.sum(masses)) * GRAVITY
    n_col = estimate_column_count(building.footprint_length, building.footprint_width)

    axial_per_column_n = total_weight_n / n_col
    allowable = building.primary_material.allowable_axial_stress
    area_m2 = max(MIN_COLUMN_AREA_M2, axial_per_column_n / allowable)

    side_m = area_m2 ** 0.5
    inertia_m4 = side_m ** 4 / 12.0
    return area_m2, inertia_m4


# ---------------------------------------------------------------------------
# Mass
# ---------------------------------------------------------------------------

def floor_masses(building):
    """Return the lumped translational mass of each floor (kg), length ``N``.

    Per floor the mass is the sum of:
      * the floor slab (footprint area x equivalent slab thickness x density),
      * the tributary facade cladding (perimeter x story height x facade mass),
      * a service live-load allowance, and
      * the tributary column self-weight (half a story above and below).

    ``MassDistribution`` is honoured as a simple scaling of the profile: a
    top-heavy distribution biases mass toward the roof while preserving the
    total. (Kept intentionally light here; refined alongside the dynamics.)
    """
    n = building.num_stories
    area = building.footprint_length * building.footprint_width
    perimeter = 2.0 * (building.footprint_length + building.footprint_width)
    rho = building.primary_material.density

    slab = area * DEFAULT_SLAB_THICKNESS_M * rho
    facade = perimeter * building.story_height * building.facade_cladding_mass_per_area
    live = area * DEFAULT_LIVE_LOAD_KG_PER_M2

    base_floor_mass = slab + facade + live
    masses = np.full(n, base_floor_mass, dtype=float)

    # Tributary column self-weight per floor (one story height of columns).
    n_col = estimate_column_count(building.footprint_length, building.footprint_width)
    # Use the minimum column as a first estimate to avoid a circular dependency
    # with column_section (which itself needs the masses); columns are a small
    # fraction of floor mass so this approximation is immaterial.
    col_mass = n_col * MIN_COLUMN_AREA_M2 * building.story_height * rho
    masses += col_mass

    masses = _apply_mass_distribution(masses, building.mass_distribution)
    return masses


def _apply_mass_distribution(masses, distribution):
    """Rescale a uniform mass profile to honour the requested distribution.

    The total mass is preserved; only how it is shared between floors changes.
    Imported lazily to avoid a hard dependency on the enum at module import.
    """
    from core.building_structure import MassDistribution

    n = len(masses)
    if n <= 1 or distribution == MassDistribution.UNIFORM:
        return masses

    if distribution == MassDistribution.CONCENTRATED_TOP:
        total = float(np.sum(masses))
        # Linearly ramp weighting from the base (1.0) to the roof (2.0).
        weights = np.linspace(1.0, 2.0, n)
        return total * weights / np.sum(weights)

    return masses


# ---------------------------------------------------------------------------
# Stiffness
# ---------------------------------------------------------------------------

def story_shear_stiffness(building):
    """Return the lateral (shear) stiffness of each story (N/m), length ``N``.

    Each story's columns act as fixed-fixed members between rigid floor
    diaphragms, so a single column contributes ``12 E I / h**3`` and a story with
    ``n_col`` columns has stiffness ``n_col * 12 E I / h**3``. Uniform over height
    for now (the section is sized once at the base); per-story tapering can come
    later.
    """
    n = building.num_stories
    e_mod = building.primary_material.elastic_modulus
    h = building.story_height
    n_col = estimate_column_count(building.footprint_length, building.footprint_width)
    _area, inertia = column_section(building)

    k_story = n_col * 12.0 * e_mod * inertia / (h ** 3)
    return np.full(n, k_story, dtype=float)


def assemble_mass_matrix(floor_mass_array):
    """Diagonal mass matrix from a length-``N`` array of floor masses."""
    return np.diag(np.asarray(floor_mass_array, dtype=float))


def assemble_shear_stiffness_matrix(story_stiffness_array):
    """Tridiagonal shear-building stiffness matrix from per-story stiffnesses.

    ``story_stiffness_array[j]`` is the stiffness of story ``j`` connecting floor
    ``j`` to floor ``j+1`` (floor ``-1`` being the ground). For floor DOFs the
    classic assembly is::

        K[j, j]   = k[j] + k[j+1]
        K[j, j+1] = K[j+1, j] = -k[j+1]

    with ``k`` beyond the top floor taken as zero (free roof).
    """
    k = np.asarray(story_stiffness_array, dtype=float)
    n = len(k)
    K = np.zeros((n, n), dtype=float)
    for j in range(n):
        K[j, j] += k[j]
        if j + 1 < n:
            K[j, j] += k[j + 1]
            K[j, j + 1] -= k[j + 1]
            K[j + 1, j] -= k[j + 1]
    return K

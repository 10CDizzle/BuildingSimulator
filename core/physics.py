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

import math
from dataclasses import dataclass

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

def column_grid(footprint_length, footprint_width, bay_spacing=DEFAULT_BAY_SPACING_M):
    """Column grid ``(nx, ny)`` covering the footprint at ~``bay_spacing`` bays.

    ``nx`` is the number of column lines along the length (loading) direction,
    ``ny`` along the width. A minimum 2x2 grid is enforced so every building has
    corner columns.
    """
    nx = max(2, int(round(footprint_length / bay_spacing)) + 1)
    ny = max(2, int(round(footprint_width / bay_spacing)) + 1)
    return nx, ny


def estimate_column_count(footprint_length, footprint_width, bay_spacing=DEFAULT_BAY_SPACING_M):
    """Total number of vertical columns on the bay grid (``nx * ny``)."""
    nx, ny = column_grid(footprint_length, footprint_width, bay_spacing)
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


# ---------------------------------------------------------------------------
# Unified shear + flexural stiffness (Timoshenko cantilever)
# ---------------------------------------------------------------------------
#
# A pure shear building (above) captures racking but not the overall cantilever
# bending that makes tall, wall/core buildings sway in a flexural shape. Real
# structures do both, and the two deformations add in *series* (tip compliance =
# bending compliance + shear compliance), not in parallel. The clean way to get
# that coupling exactly right is a Timoshenko beam element, which carries both a
# flexural rigidity ``EI`` and a shear rigidity ``GA_s`` and reduces to the pure
# bending (Euler-Bernoulli) or pure shear limit as one rigidity dominates.
#
# We stack one element per story, fix the base, and statically condense out the
# floor rotations so the model stays at one lateral DOF per floor.

def timoshenko_story_element(EI, GA_s, length):
    """4x4 Timoshenko beam-element stiffness, DOF order ``[v1, th1, v2, th2]``.

    ``EI`` is flexural rigidity (N.m^2), ``GA_s`` the shear rigidity (N), and
    ``length`` the element length (m). The shear-deformation parameter
    ``phi = 12 EI / (GA_s L^2)`` blends the behaviour: ``phi -> 0`` gives the
    Euler-Bernoulli (pure bending) element, ``phi -> inf`` a pure shear spring.
    """
    L = length
    phi = 12.0 * EI / (GA_s * L * L)
    c = EI / ((1.0 + phi) * L ** 3)
    L2 = L * L
    return c * np.array([
        [12.0,        6.0 * L,          -12.0,       6.0 * L],
        [6.0 * L,     (4.0 + phi) * L2, -6.0 * L,    (2.0 - phi) * L2],
        [-12.0,       -6.0 * L,         12.0,        -6.0 * L],
        [6.0 * L,     (2.0 - phi) * L2, -6.0 * L,    (4.0 + phi) * L2],
    ])


def assemble_shear_flexural_stiffness(EI, GA_s, story_height, num_stories):
    """Lateral stiffness (N/m, ``N x N``) of a Timoshenko cantilever.

    ``EI`` and ``GA_s`` may be scalars (uniform over height) or length-``N``
    arrays (per story). The base is fixed; floor rotations are statically
    condensed out so the result is in terms of the ``N`` floor lateral
    displacements only.
    """
    n = num_stories
    EI = np.broadcast_to(np.asarray(EI, dtype=float), (n,))
    GA_s = np.broadcast_to(np.asarray(GA_s, dtype=float), (n,))
    h = np.broadcast_to(np.asarray(story_height, dtype=float), (n,))

    # Global node DOFs: node 0 = base, nodes 1..N = floors; each node [v, theta].
    ndof = 2 * (n + 1)
    Kg = np.zeros((ndof, ndof), dtype=float)
    for e in range(1, n + 1):  # element e connects node e-1 to node e
        ke = timoshenko_story_element(EI[e - 1], GA_s[e - 1], h[e - 1])
        dofs = [2 * (e - 1), 2 * (e - 1) + 1, 2 * e, 2 * e + 1]
        Kg[np.ix_(dofs, dofs)] += ke

    # Drop the fixed base node (DOFs 0, 1).
    free = np.arange(2, ndof)
    Kf = Kg[np.ix_(free, free)]

    # Partition into translational (even) and rotational (odd) DOFs, condense.
    trans = np.arange(0, 2 * n, 2)
    rot = np.arange(1, 2 * n, 2)
    Kvv = Kf[np.ix_(trans, trans)]
    Kvr = Kf[np.ix_(trans, rot)]
    Krv = Kf[np.ix_(rot, trans)]
    Krr = Kf[np.ix_(rot, rot)]
    K_condensed = Kvv - Kvr @ np.linalg.solve(Krr, Krv)
    # Symmetrise to clean up any round-off from the condensation.
    return 0.5 * (K_condensed + K_condensed.T)


def _system_rigidity_factors(structural_system):
    """(shear, flexural) rigidity multipliers for a structural system type.

    These multiply the column-derived baselines (racking shear and chord-action
    bending), expressing how much extra lateral rigidity a system's bracing /
    walls / core contribute. They are conceptual-design calibration factors, not
    measured constants: moment frames are shear-dominated (1, 1); braced frames
    stiffen shear; shear-wall / core / diagrid systems add large flexural
    rigidity so they sway in a cantilever (bending) shape.
    """
    from core.building_structure import StructuralSystemType as S

    factors = {
        S.FRAME_MOMENT_RESISTING:   (1.0, 1.0),
        S.FRAME_BRACED_CONCENTRIC:  (4.0, 3.0),
        S.FRAME_BRACED_ECCENTRIC:   (3.0, 2.5),
        S.SHEAR_WALLS:              (3.0, 40.0),
        S.CORE_WALL:                (2.0, 60.0),
        S.DIAGRID:                  (5.0, 50.0),
    }
    return factors.get(structural_system, (1.0, 1.0))


def flexural_inertia(building):
    """Effective second moment of area for cantilever bending (m^4).

    Column chord action: each column line at distance ``d`` from the plan
    centroid contributes ``A_col * d^2`` (parallel-axis term), summed across the
    grid. This is the bending rigidity source for a bare frame; wall/core systems
    scale it up via their flexural factor.
    """
    nx, ny = column_grid(building.footprint_length, building.footprint_width)
    area, _inertia = column_section(building)
    xs = np.linspace(-building.footprint_length / 2.0, building.footprint_length / 2.0, nx)
    return ny * area * float(np.sum(xs ** 2))


def shear_rigidity(building):
    """Story shear rigidity ``GA_s`` (N), including the system shear factor.

    Derived from the column racking stiffness of step 1: a story shear spring
    ``k`` corresponds to ``GA_s = k * h`` for an element of length ``h``.
    """
    h = building.story_height
    k_story = story_shear_stiffness(building)
    shear_mult, _ = _system_rigidity_factors(building.structural_system)
    return k_story * h * shear_mult


def flexural_rigidity(building):
    """Building flexural rigidity ``EI`` (N.m^2), including the system factor."""
    e_mod = building.primary_material.elastic_modulus
    _, flex_mult = _system_rigidity_factors(building.structural_system)
    return e_mod * flexural_inertia(building) * flex_mult


def structural_stiffness_matrix(building):
    """Unified shear+flexural lateral stiffness for a building (``N x N``)."""
    return assemble_shear_flexural_stiffness(
        EI=flexural_rigidity(building),
        GA_s=shear_rigidity(building),
        story_height=building.story_height,
        num_stories=building.num_stories,
    )


# ---------------------------------------------------------------------------
# Modal analysis
# ---------------------------------------------------------------------------

@dataclass
class ModalResult:
    """Result of a free-vibration eigen-analysis, modes sorted by frequency.

    ``frequencies`` are circular (rad/s), ``periods`` in seconds. ``mode_shapes``
    holds one mode per column, mass-normalised so ``Phi^T M Phi = I`` (hence
    ``Phi^T K Phi = diag(omega^2)``). ``participation`` is the modal participation
    factor for the given influence vector and ``effective_mass`` its square (the
    effective modal mass), which sums to the total mass.
    """
    frequencies: np.ndarray
    periods: np.ndarray
    mode_shapes: np.ndarray
    participation: np.ndarray
    effective_mass: np.ndarray


def modal_analysis(M, K, influence=None):
    """Solve the generalised eigenproblem ``K phi = omega^2 M phi``.

    Works for any symmetric positive-definite mass matrix (diagonal lumped mass
    or the consistent, coupled mass matrix of the soil-structure system). The
    problem is reduced to a symmetric standard form via the Cholesky factor of
    ``M`` (``M = L L^T``, ``A = L^-1 K L^-T``) and solved with ``eigh``.
    ``influence`` is the rigid-body displacement vector for unit ground motion
    (defaults to all-ones, i.e. uniform horizontal base motion).
    """
    M = np.asarray(M, dtype=float)
    K = np.asarray(K, dtype=float)

    L = np.linalg.cholesky(M)
    L_inv = np.linalg.inv(L)
    A = L_inv @ K @ L_inv.T
    A = 0.5 * (A + A.T)  # enforce symmetry before eigh
    eigvals, Y = np.linalg.eigh(A)

    eigvals = np.clip(eigvals, 0.0, None)  # guard tiny negative round-off
    order = np.argsort(eigvals)
    eigvals = eigvals[order]
    Y = Y[:, order]

    omega = np.sqrt(eigvals)
    periods = np.where(omega > 0.0, 2.0 * np.pi / np.maximum(omega, 1e-30), np.inf)

    # Recover mass-normalised mode shapes (Phi^T M Phi = I); fix sign so the
    # largest-magnitude component is positive for determinism.
    phi = L_inv.T @ Y
    for j in range(phi.shape[1]):
        if phi[np.argmax(np.abs(phi[:, j])), j] < 0:
            phi[:, j] *= -1.0

    n = M.shape[0]
    r = np.ones(n) if influence is None else np.asarray(influence, dtype=float)
    participation = phi.T @ (M @ r)

    return ModalResult(omega, periods, phi, participation, participation ** 2)


def building_modal_analysis(building):
    """Convenience: modal analysis from a building's mass and stiffness."""
    M = assemble_mass_matrix(floor_masses(building))
    K = structural_stiffness_matrix(building)
    return modal_analysis(M, K)


# ---------------------------------------------------------------------------
# Rayleigh (proportional) damping
# ---------------------------------------------------------------------------

def rayleigh_coefficients(zeta_i, omega_i, omega_j, zeta_j=None):
    """Mass/stiffness proportional coefficients ``(alpha, beta)``.

    Chosen so ``C = alpha M + beta K`` yields damping ratio ``zeta_i`` at
    frequency ``omega_i`` and ``zeta_j`` at ``omega_j`` (``zeta_j`` defaults to
    ``zeta_i``). The modal damping of such a system is
    ``zeta(omega) = alpha/(2 omega) + beta omega/2``.
    """
    if zeta_j is None:
        zeta_j = zeta_i
    a = np.array([[1.0 / (2.0 * omega_i), omega_i / 2.0],
                  [1.0 / (2.0 * omega_j), omega_j / 2.0]])
    alpha, beta = np.linalg.solve(a, np.array([zeta_i, zeta_j]))
    return float(alpha), float(beta)


def rayleigh_damping(M, K, zeta, omega_i, omega_j, zeta_j=None):
    """Rayleigh damping matrix ``C = alpha M + beta K`` (see coefficients)."""
    alpha, beta = rayleigh_coefficients(zeta, omega_i, omega_j, zeta_j)
    return alpha * np.asarray(M, dtype=float) + beta * np.asarray(K, dtype=float)


def damping_matrix(building, M, K, modal=None, anchor_modes=(1, 3)):
    """Rayleigh damping for a building, anchored at two of its modes.

    The target ratio is the building's ``effective_damping_ratio``, applied at
    the two ``anchor_modes`` (1-based; clamped to the available modes). A single
    mode degenerates to mass-proportional damping that hits the target exactly.
    """
    if modal is None:
        modal = modal_analysis(M, K)
    n = len(modal.frequencies)
    zeta = building.effective_damping_ratio

    i = min(anchor_modes[0], n) - 1
    j = min(anchor_modes[1], n) - 1
    if i == j:
        # Single available mode: C = 2 zeta omega M reproduces zeta at that mode.
        return 2.0 * zeta * modal.frequencies[i] * np.asarray(M, dtype=float)
    return rayleigh_damping(M, K, zeta, modal.frequencies[i], modal.frequencies[j])


# ---------------------------------------------------------------------------
# Time integration (Newmark-beta)
# ---------------------------------------------------------------------------

class NewmarkIntegrator:
    """Newmark-beta direct time integrator for ``M u'' + C u' + K u = F(t)``.

    Defaults to the *average-acceleration* (constant-average-acceleration)
    scheme (gamma=1/2, beta=1/4), which is unconditionally stable and
    second-order accurate -- the standard choice in earthquake engineering. It
    does not suffer the amplitude blow-up that an explicit scheme would on the
    stiff upper modes at a 1/60 s frame step.

    The effective stiffness is constant while the structure is linear, so it is
    inverted once up front and reused every step. Call :meth:`update_system`
    when the stiffness or damping changes (e.g. a story fails or the soil
    softens) to refactorise.
    """

    def __init__(self, M, C, K, dt, gamma=0.5, beta=0.25):
        self.M = np.asarray(M, dtype=float)
        self.C = np.asarray(C, dtype=float)
        self.K = np.asarray(K, dtype=float)
        self.dt = float(dt)
        self.gamma = float(gamma)
        self.beta = float(beta)
        self._build()

    def _build(self):
        dt, beta, gamma = self.dt, self.beta, self.gamma
        # Integration constants (Newmark, e.g. Chopra "Dynamics of Structures").
        self.c0 = 1.0 / (beta * dt * dt)
        self.c1 = gamma / (beta * dt)
        self.c2 = 1.0 / (beta * dt)
        self.c3 = 1.0 / (2.0 * beta) - 1.0
        self.c4 = gamma / beta - 1.0
        self.c5 = dt * (gamma / (2.0 * beta) - 1.0)
        self.c6 = dt * (1.0 - gamma)
        self.c7 = dt * gamma

        K_eff = self.K + self.c0 * self.M + self.c1 * self.C
        self._K_eff_inv = np.linalg.inv(K_eff)

    def update_system(self, K=None, C=None):
        """Replace the stiffness and/or damping matrices and refactorise."""
        if K is not None:
            self.K = np.asarray(K, dtype=float)
        if C is not None:
            self.C = np.asarray(C, dtype=float)
        self._build()

    def initial_acceleration(self, u, v, F):
        """Acceleration consistent with the equation of motion at t=0."""
        u = np.asarray(u, dtype=float)
        v = np.asarray(v, dtype=float)
        F = np.asarray(F, dtype=float)
        return np.linalg.solve(self.M, F - self.C @ v - self.K @ u)

    def step(self, u, v, a, F_next):
        """Advance one step. Returns the new ``(u, v, a)`` at ``t + dt``.

        ``F_next`` is the external force vector at the end of the step.
        """
        u = np.asarray(u, dtype=float)
        v = np.asarray(v, dtype=float)
        a = np.asarray(a, dtype=float)
        F_next = np.asarray(F_next, dtype=float)

        F_eff = (F_next
                 + self.M @ (self.c0 * u + self.c2 * v + self.c3 * a)
                 + self.C @ (self.c1 * u + self.c4 * v + self.c5 * a))
        u_next = self._K_eff_inv @ F_eff
        a_next = self.c0 * (u_next - u) - self.c2 * v - self.c3 * a
        v_next = v + self.c6 * a + self.c7 * a_next
        return u_next, v_next, a_next


# ---------------------------------------------------------------------------
# Soil-structure interaction (foundation sway + rocking DOFs)
# ---------------------------------------------------------------------------
#
# A fixed-base model assumes the building rises from rigid rock. Real soil
# deforms: the foundation can translate (sway) and rotate (rock) on the soil,
# which lengthens the natural period and lets liquefaction / scour show up as a
# physically meaningful loss of support rather than a tuned stiffness fudge.
#
# We append two DOFs -- foundation sway ``u_f`` and rocking ``theta_f`` -- to the
# N structural DOFs, supported by soil springs and radiation dashpots. Writing
# the structural DOFs as distortions relative to the (translating, rocking) base
# keeps the coupled mass, damping, and stiffness matrices symmetric, and the
# rigid-soil limit cleanly recovers the fixed-base equations.

@dataclass
class SoilProfile:
    """Homogeneous half-space soil characterised by its shear-wave velocity."""
    shear_wave_velocity: float       # V_s (m/s)
    density: float = 1900.0          # kg/m^3
    poisson: float = 0.35            # dimensionless

    @property
    def shear_modulus(self):
        """G = rho * V_s^2 (Pa)."""
        return self.density * self.shear_wave_velocity ** 2

    def with_shear_modulus_factor(self, factor):
        """A softened copy with the shear modulus scaled by ``factor``.

        Used to model liquefaction / scour: ``G`` scales with ``V_s^2``, so the
        velocity is scaled by ``sqrt(factor)``.
        """
        return SoilProfile(self.shear_wave_velocity * math.sqrt(factor),
                           self.density, self.poisson)


# Representative profiles (V_s bands roughly per site-class usage).
ROCK_SOIL = SoilProfile(shear_wave_velocity=1200.0)
FIRM_SOIL = SoilProfile(shear_wave_velocity=400.0)
MEDIUM_SOIL = SoilProfile(shear_wave_velocity=250.0)
SOFT_SOIL = SoilProfile(shear_wave_velocity=150.0)


def floor_heights(building):
    """Heights of each floor above the base (m), length ``N``."""
    return np.arange(1, building.num_stories + 1) * building.story_height


def foundation_radii(building):
    """Equivalent circular foundation radii ``(sway, rocking)`` (m).

    The footprint is matched to an equivalent disc by area for sway and by
    second moment of area for rocking (bending about the width axis, since the
    building is loaded along its length).
    """
    L = building.footprint_length
    W = building.footprint_width
    area = L * W
    r_sway = math.sqrt(area / math.pi)
    second_moment = W * L ** 3 / 12.0
    r_rock = (4.0 * second_moment / math.pi) ** 0.25
    return r_sway, r_rock


def soil_stiffness(building, soil):
    """Static soil sway and rocking stiffness ``(k_h, k_r)`` (Gazetas/halfspace)."""
    G = soil.shear_modulus
    nu = soil.poisson
    r_h, r_r = foundation_radii(building)
    k_h = 8.0 * G * r_h / (2.0 - nu)
    k_r = 8.0 * G * r_r ** 3 / (3.0 * (1.0 - nu))
    return k_h, k_r


def soil_damping(building, soil):
    """Soil radiation dashpots ``(c_h, c_r)`` for sway and rocking (cone model)."""
    rho = soil.density
    vs = soil.shear_wave_velocity
    nu = soil.poisson
    L = building.footprint_length
    W = building.footprint_width
    area = L * W
    second_moment = W * L ** 3 / 12.0
    v_la = 3.4 * vs / (math.pi * (1.0 - nu))  # Lysmer's analog velocity
    c_h = rho * vs * area
    c_r = rho * v_la * second_moment
    return c_h, c_r


def foundation_mass(building, mat_density=2400.0, thickness=1.0):
    """Foundation mat mass and rocking inertia ``(m0, I0)``."""
    L = building.footprint_length
    W = building.footprint_width
    m0 = L * W * thickness * mat_density
    I0 = m0 * (L ** 2) / 12.0
    return m0, I0


def assemble_ssi_matrices(M_s, C_s, K_s, floor_mass, z, m0, I0, k_h, k_r, c_h, c_r):
    """Assemble the coupled (N+2)-DOF soil-structure system.

    DOF order is ``[v_1..v_N, u_f, theta_f]`` where ``v_i`` are floor distortions
    relative to the base, ``u_f`` is foundation sway and ``theta_f`` rocking.
    Returns ``(M, C, K, influence)``; the seismic load is ``-M @ influence * a_g``
    with ``influence`` a unit in the sway DOF.
    """
    m = np.asarray(floor_mass, dtype=float)
    z = np.asarray(z, dtype=float)
    n = len(m)
    mz = m * z
    m_total = float(m.sum()) + m0
    first_moment = float((m * z).sum())
    second_moment = float((m * z * z).sum()) + I0

    size = n + 2
    M = np.zeros((size, size))
    C = np.zeros((size, size))
    K = np.zeros((size, size))

    M[:n, :n] = M_s
    M[:n, n] = m
    M[n, :n] = m
    M[:n, n + 1] = mz
    M[n + 1, :n] = mz
    M[n, n] = m_total
    M[n, n + 1] = first_moment
    M[n + 1, n] = first_moment
    M[n + 1, n + 1] = second_moment

    K[:n, :n] = K_s
    K[n, n] = k_h
    K[n + 1, n + 1] = k_r

    C[:n, :n] = C_s
    C[n, n] = c_h
    C[n + 1, n + 1] = c_r

    influence = np.zeros(size)
    influence[n] = 1.0  # unit ground motion = unit foundation sway
    return M, C, K, influence


def build_ssi_system(building, soil):
    """Convenience: full SSI ``(M, C, K, influence)`` for a building on soil."""
    M_s = assemble_mass_matrix(floor_masses(building))
    K_s = structural_stiffness_matrix(building)
    modal = modal_analysis(M_s, K_s)
    C_s = damping_matrix(building, M_s, K_s, modal)

    m = floor_masses(building)
    z = floor_heights(building)
    m0, I0 = foundation_mass(building)
    k_h, k_r = soil_stiffness(building, soil)
    c_h, c_r = soil_damping(building, soil)
    return assemble_ssi_matrices(M_s, C_s, K_s, m, z, m0, I0, k_h, k_r, c_h, c_r)

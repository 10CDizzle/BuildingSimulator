"""Tests for the structural-dynamics core (core/physics.py).

Run from the repository root with the project venv:

    .\\.venv\\Scripts\\python.exe -m unittest discover -s tests

These use the standard-library ``unittest`` so no extra dependency is needed.
"""

import math
import os
import tempfile
import unittest

import numpy as np

from core import physics
from core.building_structure import (
    Building, CONCRETE, STEEL, MassDistribution, StructuralSystemType,
)


def uniform_shear_building_frequencies(n, k, m):
    """Closed-form natural circular frequencies of a uniform shear building.

    For ``n`` equal masses ``m`` joined by ``n`` equal story stiffnesses ``k``
    (fixed base, free top), the exact natural frequencies are

        omega_r = 2 sqrt(k/m) sin( (2r-1) pi / (2(2n+1)) ),  r = 1..n

    Returned sorted ascending.
    """
    base = 2.0 * math.sqrt(k / m)
    freqs = [base * math.sin((2 * r - 1) * math.pi / (2 * (2 * n + 1))) for r in range(1, n + 1)]
    return np.array(sorted(freqs))


def natural_frequencies(M, K):
    """Ascending natural circular frequencies for M u'' + K u = 0."""
    m_diag = np.diag(M)
    inv_sqrt = np.diag(1.0 / np.sqrt(m_diag))
    a = inv_sqrt @ K @ inv_sqrt
    eigvals = np.linalg.eigvalsh(a)
    eigvals = np.clip(eigvals, 0.0, None)  # guard tiny negative round-off
    return np.sqrt(np.sort(eigvals))


class AssemblyTests(unittest.TestCase):
    def test_mass_matrix_is_diagonal_with_given_values(self):
        masses = [1000.0, 2000.0, 3000.0]
        M = physics.assemble_mass_matrix(masses)
        self.assertEqual(M.shape, (3, 3))
        np.testing.assert_allclose(np.diag(M), masses)
        # Off-diagonal entries must all be zero.
        np.testing.assert_allclose(M - np.diag(np.diag(M)), 0.0)

    def test_shear_stiffness_matrix_structure(self):
        k = [100.0, 200.0, 300.0]
        K = physics.assemble_shear_stiffness_matrix(k)
        # Symmetric.
        np.testing.assert_allclose(K, K.T)
        # Tridiagonal entries per the shear-building assembly.
        expected = np.array([
            [k[0] + k[1], -k[1],        0.0],
            [-k[1],       k[1] + k[2],  -k[2]],
            [0.0,         -k[2],        k[2]],
        ])
        np.testing.assert_allclose(K, expected)

    def test_single_story_reduces_to_sdof(self):
        K = physics.assemble_shear_stiffness_matrix([500.0])
        np.testing.assert_allclose(K, [[500.0]])


class UniformShearBuildingTests(unittest.TestCase):
    """The headline assembly check: frequencies match the closed-form solution."""

    def test_frequencies_match_closed_form(self):
        m, k = 1500.0, 4.0e6
        for n in (1, 2, 3, 5, 10):
            with self.subTest(stories=n):
                M = physics.assemble_mass_matrix(np.full(n, m))
                K = physics.assemble_shear_stiffness_matrix(np.full(n, k))
                computed = natural_frequencies(M, K)
                expected = uniform_shear_building_frequencies(n, k, m)
                np.testing.assert_allclose(computed, expected, rtol=1e-9, atol=0.0)


class BuildingDerivationTests(unittest.TestCase):
    def _building(self, **kw):
        params = dict(num_stories=5, story_height=3.0, footprint_length=15.0,
                      footprint_width=10.0, primary_material=CONCRETE)
        params.update(kw)
        return Building(**params)

    def test_floor_masses_positive_and_correct_length(self):
        b = self._building()
        masses = physics.floor_masses(b)
        self.assertEqual(len(masses), b.num_stories)
        self.assertTrue(np.all(masses > 0.0))

    def test_concentrated_top_preserves_total_but_biases_upward(self):
        uniform = self._building(mass_distribution=MassDistribution.UNIFORM)
        top = self._building(mass_distribution=MassDistribution.CONCENTRATED_TOP)
        mu = physics.floor_masses(uniform)
        mt = physics.floor_masses(top)
        # Total mass preserved.
        self.assertAlmostEqual(float(np.sum(mu)), float(np.sum(mt)), places=3)
        # Roof heavier than base under the top-concentrated distribution.
        self.assertGreater(mt[-1], mt[0])

    def test_column_area_respects_minimum(self):
        b = self._building(num_stories=1, footprint_length=5.0, footprint_width=5.0)
        area, inertia = physics.column_section(b)
        self.assertGreaterEqual(area, physics.MIN_COLUMN_AREA_M2)
        self.assertGreater(inertia, 0.0)

    def test_taller_building_needs_larger_columns(self):
        short = self._building(num_stories=3)
        tall = self._building(num_stories=20)
        self.assertGreater(physics.column_section(tall)[0],
                           physics.column_section(short)[0])

    def test_story_stiffness_positive_and_uniform(self):
        b = self._building()
        k = physics.story_shear_stiffness(b)
        self.assertEqual(len(k), b.num_stories)
        self.assertTrue(np.all(k > 0.0))
        np.testing.assert_allclose(k, k[0])  # uniform over height for now

    def test_stiffer_material_gives_higher_frequency(self):
        concrete = self._building(primary_material=CONCRETE)
        steel = self._building(primary_material=STEEL)
        f_concrete = natural_frequencies(
            physics.assemble_mass_matrix(physics.floor_masses(concrete)),
            physics.assemble_shear_stiffness_matrix(physics.story_shear_stiffness(concrete)),
        )[0]
        f_steel = natural_frequencies(
            physics.assemble_mass_matrix(physics.floor_masses(steel)),
            physics.assemble_shear_stiffness_matrix(physics.story_shear_stiffness(steel)),
        )[0]
        self.assertGreater(f_steel, f_concrete)

    def test_fundamental_period_in_realistic_band(self):
        """A mid-rise frame should land in a believable period range.

        Empirical code estimates put a 5-story building near ~0.5 s. We only
        assert a generous band so the test guards against order-of-magnitude
        errors in sizing/assembly rather than pinning an exact value.
        """
        b = self._building()
        omega1 = natural_frequencies(
            physics.assemble_mass_matrix(physics.floor_masses(b)),
            physics.assemble_shear_stiffness_matrix(physics.story_shear_stiffness(b)),
        )[0]
        period = 2.0 * math.pi / omega1
        self.assertTrue(0.2 < period < 1.5, f"fundamental period {period:.3f}s out of band")


class ShearFlexuralStiffnessTests(unittest.TestCase):
    """Unified Timoshenko cantilever: limits and the exact coupling."""

    def test_coupled_tip_deflection_is_series_of_bending_and_shear(self):
        """Tip deflection under a unit roof load = H^3/(3EI) + H/(GA_s).

        This is the exact Timoshenko cantilever result and simultaneously
        exercises the element, assembly, base fixity, and rotation condensation.
        """
        EI, GA_s, h, n = 5.0e11, 3.0e8, 3.0, 8
        H = n * h
        K = physics.assemble_shear_flexural_stiffness(EI, GA_s, h, n)
        F = np.zeros(n)
        F[-1] = 1.0  # unit load at the roof
        u = np.linalg.solve(K, F)
        expected_tip = H ** 3 / (3.0 * EI) + H / GA_s
        self.assertAlmostEqual(u[-1], expected_tip, delta=expected_tip * 1e-9)

    def test_pure_flexural_single_story_tip_stiffness(self):
        """With negligible shear flexibility, a 1-element cantilever -> 3EI/L^3."""
        EI, h = 2.0e11, 3.0
        GA_s = 1.0e18  # effectively rigid in shear
        K = physics.assemble_shear_flexural_stiffness(EI, GA_s, h, 1)
        self.assertAlmostEqual(K[0, 0], 3.0 * EI / h ** 3, delta=3.0 * EI / h ** 3 * 1e-6)

    def test_pure_shear_limit_matches_shear_building(self):
        """With dominant bending rigidity, the matrix -> the shear building K."""
        GA_s, h, n = 2.5e8, 3.0, 6
        EI = 1.0e18  # effectively rigid in bending -> pure shear
        K_tim = physics.assemble_shear_flexural_stiffness(EI, GA_s, h, n)
        K_shear = physics.assemble_shear_stiffness_matrix(np.full(n, GA_s / h))
        np.testing.assert_allclose(K_tim, K_shear, rtol=1e-6, atol=1.0)

    def test_matrix_is_symmetric_and_positive_definite(self):
        K = physics.assemble_shear_flexural_stiffness(4.0e11, 3.0e8, 3.0, 5)
        np.testing.assert_allclose(K, K.T, rtol=0, atol=1e-3)
        self.assertTrue(np.all(np.linalg.eigvalsh(K) > 0.0))

    def test_added_shear_flexibility_softens_structure(self):
        """Finite shear rigidity must make a frame more flexible than pure bending."""
        EI, GA_s, h, n = 5.0e11, 3.0e8, 3.0, 8
        K_coupled = physics.assemble_shear_flexural_stiffness(EI, GA_s, h, n)
        K_bending = physics.assemble_shear_flexural_stiffness(EI, 1.0e18, h, n)
        F = np.zeros(n)
        F[-1] = 1.0
        tip_coupled = np.linalg.solve(K_coupled, F)[-1]
        tip_bending = np.linalg.solve(K_bending, F)[-1]
        self.assertGreater(tip_coupled, tip_bending)


class StructuralSystemTests(unittest.TestCase):
    def _building(self, system):
        return Building(num_stories=12, story_height=3.0, footprint_length=20.0,
                        footprint_width=15.0, primary_material=CONCRETE,
                        structural_system=system)

    def _fundamental_period(self, b):
        M = physics.assemble_mass_matrix(physics.floor_masses(b))
        K = physics.structural_stiffness_matrix(b)
        omega1 = natural_frequencies(M, K)[0]
        return 2.0 * math.pi / omega1

    def test_core_wall_stiffer_than_moment_frame(self):
        """Flexural-dominated systems should sway less (shorter period)."""
        frame = self._building(StructuralSystemType.FRAME_MOMENT_RESISTING)
        core = self._building(StructuralSystemType.CORE_WALL)
        self.assertLess(self._fundamental_period(core), self._fundamental_period(frame))

    def test_braced_frame_stiffer_than_moment_frame(self):
        frame = self._building(StructuralSystemType.FRAME_MOMENT_RESISTING)
        braced = self._building(StructuralSystemType.FRAME_BRACED_CONCENTRIC)
        self.assertLess(self._fundamental_period(braced), self._fundamental_period(frame))

    def test_structural_matrix_well_formed(self):
        b = self._building(StructuralSystemType.SHEAR_WALLS)
        K = physics.structural_stiffness_matrix(b)
        self.assertEqual(K.shape, (b.num_stories, b.num_stories))
        np.testing.assert_allclose(K, K.T, rtol=0, atol=K.max() * 1e-9)
        self.assertTrue(np.all(np.linalg.eigvalsh(K) > 0.0))


class ModalAnalysisTests(unittest.TestCase):
    """Eigen-analysis against a hand-solvable 2-DOF system."""

    def setUp(self):
        # m = k = 1; K is the 2-story shear building matrix.
        self.M = np.eye(2)
        self.K = np.array([[2.0, -1.0], [-1.0, 1.0]])
        # Exact: omega^2 = (3 -+ sqrt 5)/2.
        self.exact_omega = np.sqrt(np.sort([(3 - math.sqrt(5)) / 2, (3 + math.sqrt(5)) / 2]))

    def test_frequencies_match_hand_solution(self):
        res = physics.modal_analysis(self.M, self.K)
        np.testing.assert_allclose(res.frequencies, self.exact_omega, rtol=1e-12)

    def test_periods_are_two_pi_over_omega(self):
        res = physics.modal_analysis(self.M, self.K)
        np.testing.assert_allclose(res.periods, 2.0 * math.pi / res.frequencies, rtol=1e-12)

    def test_mode_shapes_are_mass_and_stiffness_orthonormal(self):
        res = physics.modal_analysis(self.M, self.K)
        phi = res.mode_shapes
        np.testing.assert_allclose(phi.T @ self.M @ phi, np.eye(2), atol=1e-12)
        np.testing.assert_allclose(phi.T @ self.K @ phi,
                                   np.diag(res.frequencies ** 2), atol=1e-12)

    def test_effective_modal_mass_sums_to_total_mass(self):
        res = physics.modal_analysis(self.M, self.K)
        self.assertAlmostEqual(float(np.sum(res.effective_mass)),
                               float(np.sum(np.diag(self.M))), places=10)

    def test_building_modal_first_period_matches_direct_solve(self):
        b = Building(num_stories=8, story_height=3.0, footprint_length=18.0,
                     footprint_width=14.0, primary_material=CONCRETE)
        res = physics.building_modal_analysis(b)
        direct = natural_frequencies(physics.assemble_mass_matrix(physics.floor_masses(b)),
                                     physics.structural_stiffness_matrix(b))
        np.testing.assert_allclose(res.frequencies, direct, rtol=1e-10)
        # Fundamental mode shape should grow monotonically up the height.
        first = res.mode_shapes[:, 0]
        self.assertTrue(np.all(np.diff(np.abs(first)) > 0))


class RayleighDampingTests(unittest.TestCase):
    def test_coefficients_match_equal_zeta_closed_form(self):
        zeta, wi, wj = 0.05, 2.0, 9.0
        alpha, beta = physics.rayleigh_coefficients(zeta, wi, wj)
        self.assertAlmostEqual(alpha, zeta * 2 * wi * wj / (wi + wj), places=12)
        self.assertAlmostEqual(beta, zeta * 2 / (wi + wj), places=12)

    def test_damping_reproduces_target_ratio_at_anchor_modes(self):
        M = np.diag([1500.0, 1500.0, 1500.0])
        K = physics.assemble_shear_stiffness_matrix(np.full(3, 4.0e6))
        res = physics.modal_analysis(M, K)
        zeta = 0.05
        wi, wj = res.frequencies[0], res.frequencies[2]
        C = physics.rayleigh_damping(M, K, zeta, wi, wj)
        phi = res.mode_shapes
        # Modal damping ratio for mass-normalised modes: zeta_k = phi^T C phi / (2 omega_k).
        for idx in (0, 2):
            modal_c = phi[:, idx] @ C @ phi[:, idx]
            zeta_k = modal_c / (2.0 * res.frequencies[idx])
            self.assertAlmostEqual(zeta_k, zeta, places=10)

    def test_intermediate_mode_is_underdamped_relative_to_anchors(self):
        M = np.diag([1500.0, 1500.0, 1500.0])
        K = physics.assemble_shear_stiffness_matrix(np.full(3, 4.0e6))
        res = physics.modal_analysis(M, K)
        zeta = 0.05
        C = physics.rayleigh_damping(M, K, zeta, res.frequencies[0], res.frequencies[2])
        phi = res.mode_shapes
        zeta_mid = (phi[:, 1] @ C @ phi[:, 1]) / (2.0 * res.frequencies[1])
        # Rayleigh damping dips between the two anchor frequencies.
        self.assertTrue(0.0 < zeta_mid < zeta)

    def test_building_damping_matrix_is_symmetric(self):
        b = Building(num_stories=6, story_height=3.0, footprint_length=15.0,
                     footprint_width=10.0, primary_material=CONCRETE)
        M = physics.assemble_mass_matrix(physics.floor_masses(b))
        K = physics.structural_stiffness_matrix(b)
        C = physics.damping_matrix(b, M, K)
        np.testing.assert_allclose(C, C.T, rtol=0, atol=C.max() * 1e-12)


class NewmarkIntegratorTests(unittest.TestCase):
    """Time integration against analytical single- and multi-DOF results."""

    def test_sdof_damped_free_vibration_matches_analytical(self):
        m, k, zeta = 2.0, 800.0, 0.05
        omega = math.sqrt(k / m)
        c = 2.0 * zeta * omega * m
        omega_d = omega * math.sqrt(1.0 - zeta ** 2)

        M, C, K = np.array([[m]]), np.array([[c]]), np.array([[k]])
        dt = (2 * math.pi / omega) / 400.0  # ~400 steps per period
        integ = physics.NewmarkIntegrator(M, C, K, dt)

        u = np.array([1.0]); v = np.array([0.0])
        a = integ.initial_acceleration(u, v, np.zeros(1))

        def analytical(t):
            return math.exp(-zeta * omega * t) * (
                math.cos(omega_d * t) + (zeta * omega / omega_d) * math.sin(omega_d * t))

        t = 0.0
        for _ in range(1200):
            u, v, a = integ.step(u, v, a, np.zeros(1))
            t += dt
            self.assertAlmostEqual(u[0], analytical(t), delta=2e-3)

    def test_undamped_energy_is_conserved_over_long_run(self):
        """Average-acceleration Newmark must not pump or bleed energy."""
        m, k = 1.5, 1200.0
        M, C, K = np.array([[m]]), np.array([[0.0]]), np.array([[k]])
        omega = math.sqrt(k / m)
        dt = (2 * math.pi / omega) / 60.0
        integ = physics.NewmarkIntegrator(M, C, K, dt)

        u = np.array([0.05]); v = np.array([0.0])
        a = integ.initial_acceleration(u, v, np.zeros(1))
        e0 = 0.5 * m * v[0] ** 2 + 0.5 * k * u[0] ** 2

        for _ in range(60 * 200):  # 200 periods
            u, v, a = integ.step(u, v, a, np.zeros(1))
            e = 0.5 * m * v[0] ** 2 + 0.5 * k * u[0] ** 2
            self.assertLess(abs(e - e0) / e0, 1e-3)

    def test_constant_load_converges_to_static_solution(self):
        M = np.diag([1000.0, 1000.0, 1000.0])
        K = physics.assemble_shear_stiffness_matrix(np.full(3, 5.0e5))
        res = physics.modal_analysis(M, K)
        C = physics.rayleigh_damping(M, K, 0.1, res.frequencies[0], res.frequencies[2])
        dt = res.periods[0] / 50.0
        integ = physics.NewmarkIntegrator(M, C, K, dt)

        F = np.array([1000.0, 2000.0, 1500.0])
        u = np.zeros(3); v = np.zeros(3); a = integ.initial_acceleration(u, v, F)
        for _ in range(5000):
            u, v, a = integ.step(u, v, a, F)
        np.testing.assert_allclose(u, np.linalg.solve(K, F), rtol=1e-4)

    def test_update_system_refactorises(self):
        M = np.diag([1000.0, 1000.0])
        K1 = physics.assemble_shear_stiffness_matrix(np.full(2, 4.0e5))
        K2 = physics.assemble_shear_stiffness_matrix(np.full(2, 1.0e5))  # softened
        C = np.zeros((2, 2))
        integ = physics.NewmarkIntegrator(M, np.diag([2e4, 2e4]), K1, 0.01)

        F = np.array([500.0, 800.0])
        integ.update_system(K=K2)
        u = np.zeros(2); v = np.zeros(2); a = integ.initial_acceleration(u, v, F)
        for _ in range(8000):
            u, v, a = integ.step(u, v, a, F)
        np.testing.assert_allclose(u, np.linalg.solve(K2, F), rtol=1e-3)

    def test_resonant_forcing_amplifies(self):
        """Harmonic forcing at the natural frequency should build a large response."""
        m, k, zeta = 1.0, 400.0, 0.02
        omega = math.sqrt(k / m)
        c = 2 * zeta * omega * m
        M, C, K = np.array([[m]]), np.array([[c]]), np.array([[k]])
        dt = (2 * math.pi / omega) / 200.0
        integ = physics.NewmarkIntegrator(M, C, K, dt)

        u = np.zeros(1); v = np.zeros(1); a = np.zeros(1)
        peak_on, peak_off = 0.0, 0.0
        t = 0.0
        for _ in range(200 * 40):
            t += dt
            u, v, a = integ.step(u, v, a, np.array([math.sin(omega * t)]))
            peak_on = max(peak_on, abs(u[0]))
        # Re-run far above resonance: response stays near quasi-static.
        u = np.zeros(1); v = np.zeros(1); a = np.zeros(1); t = 0.0
        for _ in range(200 * 40):
            t += dt
            u, v, a = integ.step(u, v, a, np.array([math.sin(5 * omega * t)]))
            peak_off = max(peak_off, abs(u[0]))
        self.assertGreater(peak_on, 5 * peak_off)


class SoilStructureInteractionTests(unittest.TestCase):
    def _building(self, **kw):
        params = dict(num_stories=10, story_height=3.0, footprint_length=20.0,
                      footprint_width=15.0, primary_material=CONCRETE)
        params.update(kw)
        return Building(**params)

    def _fixed_base_period(self, b):
        M = physics.assemble_mass_matrix(physics.floor_masses(b))
        K = physics.structural_stiffness_matrix(b)
        return physics.modal_analysis(M, K).periods[0]

    def _ssi_period(self, b, soil):
        M, C, K, _ = physics.build_ssi_system(b, soil)
        return physics.modal_analysis(M, K).periods[0]

    def test_matrices_are_symmetric(self):
        b = self._building()
        M, C, K, _ = physics.build_ssi_system(b, physics.MEDIUM_SOIL)
        for name, A in (("M", M), ("C", C), ("K", K)):
            np.testing.assert_allclose(A, A.T, rtol=0, atol=abs(A).max() * 1e-9,
                                       err_msg=f"{name} not symmetric")

    def test_influence_picks_out_translational_mass(self):
        b = self._building()
        M, C, K, influence = physics.build_ssi_system(b, physics.MEDIUM_SOIL)
        n = b.num_stories
        m = physics.floor_masses(b)
        z = physics.floor_heights(b)
        m0, _I0 = physics.foundation_mass(b)
        load = M @ influence  # = [m ; m_total ; first_moment]
        np.testing.assert_allclose(load[:n], m, rtol=1e-12)
        self.assertAlmostEqual(load[n], float(m.sum()) + m0, places=3)
        self.assertAlmostEqual(load[n + 1], float((m * z).sum()), places=3)

    def test_rigid_soil_recovers_fixed_base(self):
        """As the soil stiffens, the first SSI period -> the fixed-base period."""
        b = self._building()
        rigid = physics.SoilProfile(shear_wave_velocity=40000.0)  # ~rigid rock
        self.assertAlmostEqual(self._ssi_period(b, rigid), self._fixed_base_period(b),
                               delta=self._fixed_base_period(b) * 0.02)

    def test_soft_soil_lengthens_period(self):
        b = self._building()
        fixed = self._fixed_base_period(b)
        self.assertGreater(self._ssi_period(b, physics.SOFT_SOIL), fixed)

    def test_softer_soil_lengthens_period_more(self):
        b = self._building()
        firm = self._ssi_period(b, physics.FIRM_SOIL)
        soft = self._ssi_period(b, physics.SOFT_SOIL)
        self.assertGreater(soft, firm)

    def test_liquefaction_strongly_lengthens_period(self):
        """Near-total loss of soil stiffness must noticeably lengthen the period.

        The increase is bounded by the (structure-dominated) fixed-base period --
        SSI contributions add in quadrature -- so a ~25%+ jump is the expected
        signature for a stiff structure, not an unbounded one.
        """
        b = self._building()
        firm = self._ssi_period(b, physics.FIRM_SOIL)
        liquefied = self._ssi_period(b, physics.FIRM_SOIL.with_shear_modulus_factor(0.02))
        self.assertGreater(liquefied, 1.25 * firm)

    def test_softer_soil_increases_compliance(self):
        """Soil springs must drop when the shear modulus drops."""
        b = self._building()
        kh_firm, kr_firm = physics.soil_stiffness(b, physics.FIRM_SOIL)
        kh_soft, kr_soft = physics.soil_stiffness(b, physics.SOFT_SOIL)
        self.assertLess(kh_soft, kh_firm)
        self.assertLess(kr_soft, kr_firm)

    def test_ssi_system_is_positive_definite(self):
        b = self._building()
        M, C, K, _ = physics.build_ssi_system(b, physics.MEDIUM_SOIL)
        self.assertTrue(np.all(np.linalg.eigvalsh(M) > 0.0))
        self.assertTrue(np.all(np.linalg.eigvalsh(K) > 0.0))


class WindLoadTests(unittest.TestCase):
    def _building(self, **kw):
        params = dict(num_stories=10, story_height=3.0, footprint_length=20.0,
                      footprint_width=15.0, primary_material=CONCRETE)
        params.update(kw)
        return Building(**params)

    def test_profile_increases_with_height_and_matches_reference(self):
        self.assertAlmostEqual(physics.wind_speed_profile(10.0, 30.0, z_ref=10.0), 30.0)
        speeds = physics.wind_speed_profile(np.array([3.0, 10.0, 30.0]), 30.0)
        self.assertTrue(np.all(np.diff(speeds) > 0))

    def test_mean_force_grows_up_the_height(self):
        wind = physics.WindLoad(self._building(), reference_speed=30.0)
        f = wind.mean_force()
        self.assertEqual(len(f), 10)
        self.assertTrue(np.all(np.diff(f) > 0))  # higher floors -> faster wind -> more force

    def test_uniform_profile_matches_hand_calculation(self):
        b = self._building()
        wind = physics.WindLoad(b, reference_speed=25.0, exponent=0.0,
                                drag=1.2, air_density=1.225)
        area = b.footprint_length * b.story_height
        expected = 0.5 * 1.225 * 1.2 * 25.0 ** 2 * area
        np.testing.assert_allclose(wind.mean_force(), expected, rtol=1e-12)

    def test_gust_fluctuates_about_mean(self):
        wind = physics.WindLoad(self._building(), reference_speed=30.0,
                                turbulence_intensity=0.2, seed=1)
        samples = np.array([wind.force_at(t)[-1] for t in np.linspace(0, 60, 600)])
        mean = wind.mean_force()[-1]
        self.assertGreater(samples.max(), mean)   # gusts exceed the mean
        self.assertLess(samples.min(), mean)      # lulls fall below it
        self.assertTrue(np.all(samples >= 0.0))   # squared factor stays non-negative


class GroundMotionTests(unittest.TestCase):
    def test_harmonic_peaks_at_pga(self):
        gm = physics.HarmonicGroundMotion(pga_g=0.3, frequency_hz=2.0)
        samples = np.array([abs(gm(t)) for t in np.linspace(0, 2, 2000)])
        self.assertAlmostEqual(samples.max(), 0.3 * physics.GRAVITY, delta=1e-3)

    def test_harmonic_respects_finite_duration(self):
        gm = physics.HarmonicGroundMotion(pga_g=0.3, frequency_hz=2.0, duration=3.0)
        self.assertEqual(gm(5.0), 0.0)

    def test_synthetic_is_scaled_to_target_pga(self):
        gm = physics.SyntheticGroundMotion(pga_g=0.4, duration=15.0, seed=7)
        times, accels = gm.sample(0.005, 15.0)
        self.assertAlmostEqual(np.max(np.abs(accels)), 0.4 * physics.GRAVITY, delta=1e-2)
        self.assertEqual(gm(100.0), 0.0)  # zero outside its duration

    def test_recorded_interpolates_and_scales(self):
        times = np.array([0.0, 1.0, 2.0])
        accels = np.array([0.0, 2.0, -4.0])
        gm = physics.RecordedGroundMotion(times, accels)
        self.assertAlmostEqual(gm(0.5), 1.0)  # linear interpolation
        scaled = physics.RecordedGroundMotion(times, accels, scale_to_pga_g=0.5)
        self.assertAlmostEqual(np.max(np.abs([scaled(t) for t in times])),
                               0.5 * physics.GRAVITY, delta=1e-9)

    def test_recorded_from_two_column_file(self):
        path = os.path.join(tempfile.gettempdir(), "bs_test_record.txt")
        np.savetxt(path, np.column_stack([[0.0, 1.0, 2.0], [0.0, 1.0, 2.0]]))
        try:
            gm = physics.RecordedGroundMotion.from_file(path)
            self.assertAlmostEqual(gm(1.5), 1.5)
        finally:
            os.remove(path)


class FloodLoadTests(unittest.TestCase):
    def _building(self, **kw):
        params = dict(num_stories=10, story_height=3.0, footprint_length=20.0,
                      footprint_width=15.0, primary_material=CONCRETE)
        params.update(kw)
        return Building(**params)

    def test_no_force_above_water(self):
        b = self._building()
        F = physics.flood_lateral_force(b, water_level=0.0)
        np.testing.assert_allclose(F, 0.0)

    def test_force_increases_with_water_level(self):
        b = self._building()
        low = physics.flood_lateral_force(b, water_level=3.0).sum()
        high = physics.flood_lateral_force(b, water_level=9.0).sum()
        self.assertGreater(high, low)

    def test_submerged_story_matches_hydrostatic_resultant(self):
        b = self._building()
        # Water exactly at the top of story 1 (height h): the first story is
        # fully submerged with head h at its base -> resultant rho g width h^2/2.
        h = b.story_height
        F = physics.flood_lateral_force(b, water_level=h)
        expected = 1000.0 * physics.GRAVITY * b.footprint_length * (h ** 2) / 2.0
        self.assertAlmostEqual(F[0], expected, delta=expected * 1e-9)

    def test_buoyancy_scales_with_submerged_volume(self):
        b = self._building()
        up3, vol3 = physics.flood_buoyancy(b, 3.0)
        up6, vol6 = physics.flood_buoyancy(b, 6.0)
        self.assertAlmostEqual(up3, 1000.0 * physics.GRAVITY * vol3, places=3)
        self.assertGreater(up6, up3)


class LoadCouplingTests(unittest.TestCase):
    def test_force_maps_to_ssi_dofs(self):
        F = np.array([10.0, 20.0, 30.0])
        z = np.array([3.0, 6.0, 9.0])
        Q = physics.structural_force_to_ssi(F, z)
        self.assertEqual(len(Q), 5)
        np.testing.assert_allclose(Q[:3], F)
        self.assertAlmostEqual(Q[3], 60.0)            # sum F
        self.assertAlmostEqual(Q[4], 10 * 3 + 20 * 6 + 30 * 9)  # sum z*F

    def test_static_wind_deflection_matches_direct_solve(self):
        """End-to-end: integrate the SSI system under steady wind -> K^-1 Q."""
        b = Building(num_stories=6, story_height=3.0, footprint_length=18.0,
                     footprint_width=12.0, primary_material=CONCRETE)
        M, C, K, _ = physics.build_ssi_system(b, physics.MEDIUM_SOIL)
        wind = physics.WindLoad(b, reference_speed=30.0)
        Q = physics.structural_force_to_ssi(wind.mean_force(), physics.floor_heights(b))

        dt = physics.modal_analysis(M, K).periods[0] / 60.0
        integ = physics.NewmarkIntegrator(M, C, K, dt)
        u = np.zeros(len(Q)); v = np.zeros(len(Q)); a = integ.initial_acceleration(u, v, Q)
        for _ in range(8000):
            u, v, a = integ.step(u, v, a, Q)
        np.testing.assert_allclose(u, np.linalg.solve(K, Q), rtol=1e-3)


if __name__ == "__main__":
    unittest.main()

"""Tests for the structural-dynamics core (core/physics.py).

Run from the repository root with the project venv:

    .\\.venv\\Scripts\\python.exe -m unittest discover -s tests

These use the standard-library ``unittest`` so no extra dependency is needed.
"""

import math
import unittest

import numpy as np

from core import physics
from core.building_structure import Building, CONCRETE, STEEL, MassDistribution


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


if __name__ == "__main__":
    unittest.main()

import numpy
from scipy.special import erfc
from . import kernels as FKN

def longrange(x, delta_k, split, factor):
    """ factor shall be 3 * Omega_M / 2, if delta_k is really 1 + overdensity """

    f = numpy.empty_like(x)

    pot_k = delta_k.apply(FKN.laplace) \
                  .apply(FKN.longrange(split), out=Ellipsis)

    for d in range(x.shape[1]):
        force_d = pot_k.apply(FKN.gradient(d)) \
                  .c2r(out=Ellipsis)
        force_d.readout(x, out=f[..., d])

    f[...] *= factor

    return f

def shortrange(tree1, tree2, r_split, r_cut, r_smth, factor):
    """ factor shall be G * M0 / H0** 2 in order to match long range. 

        GM0 / H0 ** 2 = 1.0 / (4 * pi) * (V / N)  (3 * Omega_M / 2)

        computes force for all particles in tree1 due to tree2.
    """
    X = tree1.input
    Y = tree2.input

    F = numpy.zeros_like(X)
    nd = F.shape[1]

    def shortrange_kernel(r):
        u = r / (r_split * 2)
        return erfc(u) + 2 * u / numpy.pi ** 0.5 * numpy.exp(-u**2)

    def force_kernel(r, i, j):
        r, i, j = cut(r, i, j, r_smth)
        if len(r) == 0: return

        # the sign here is correct. Attacting i towards j.
        R = wrap(X[i] - Y[j], tree1.boxsize)
        s = shortrange_kernel(r)
        r3inv = 1 / r ** 3 * s
        F1 = - r3inv * R
        numpy.add.at(F, i, F1)

    tree1.root.enum(tree2.root, r_cut, process=force_kernel)
    return F * factor

def wrap(R, boxsize):
    for d, b in enumerate(boxsize):
        Rd = R[..., d]
        Rd[Rd > 0.5 * b] -= b
        Rd[Rd < -0.5 * b] += b
    return R

def cut(r, i, j, rmin):
    mask = r > rmin
    r = r[mask]
    i = i[mask]
    j = j[mask]
    return r, i, j

def timestep(tree, P, a, pt, r_cut, r_smth, factor, eta=0.03, sym=True):
    """ factor is the same as the short-range force factor, GM0 / H**2.

        This computes the time step for any particles, assuming free-falling.

        The way the formula is derived is from

        \Delta r = p 1 / (a a a E) da
        \Delta p = f 1 / (a a E) da
        f = (2 GM0 / H0**2) / r**2,

        2 is reduced mass of the pair wise system.

        free-fall assumes p = \Delta p, thus
    """

    X = tree.input
    h = numpy.zeros_like(X[..., 0])
    h[...] = numpy.inf

    E = pt.E(a)

    g = a ** 2.5 * E * (2 * factor) ** -0.5 * eta

    dg_da = 2.5 * g / a + g / E * pt.E(a, order=1) / a

    def gettimestep(r, i, j):
        r, i, j = cut(r, i, j, r_smth)
        if len(r) == 0: return

        tau = g * r ** 1.5

        if sym:
            R = wrap(X[j] - X[i], tree.boxsize)

            dR_da = (P[j] - P[i]) / (a ** 3 * E)

            RdotdR_da = numpy.einsum('ij, ij->i', R, dR_da)

            dtau_da = dg_da * r ** 1.5 \
                    + g * 1.5 * r ** -0.5 * RdotdR_da

            # symmetrize the step, according to http://arxiv.org/abs/1205.5668v1

            assert (dtau_da < 2).all() # need to add the limiter if this happens.
            
            tau = tau / (1 - 0.5 * dtau_da)

        numpy.fmin.at(h, i, tau)

    tree.root.enum(tree.root, r_cut, gettimestep)

    return h


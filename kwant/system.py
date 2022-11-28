# Copyright 2011-2020 Kwant authors.
#
# This file is part of Kwant.  It is subject to the license terms in the file
# LICENSE.rst found in the top-level directory of this distribution and at
# https://kwant-project.org/license.  A list of Kwant authors can be found in
# the file AUTHORS.rst at the top-level directory of this distribution and at
# https://kwant-project.org/authors.

"""Low-level interface of systems"""

__all__ = [
    'Site', 'SiteArray', 'SiteFamily', 'Symmetry', 'NoSymmetry',
    'System', 'VectorizedSystem', 'FiniteSystem', 'FiniteVectorizedSystem',
    'InfiniteSystem', 'InfiniteVectorizedSystem',
    'is_finite', 'is_infinite', 'is_vectorized',
]

import abc
import warnings
import operator
from copy import copy
import collections
from functools import total_ordering, lru_cache
import numpy as np
import tinyarray as ta
from . import _system
from ._common  import deprecate_args, KwantDeprecationWarning



################ Sites and Site families

class Site(tuple):
    """A site, member of a `SiteFamily`.

    Sites are the vertices of the graph which describes the tight binding
    system in a `Builder`.

    A site is uniquely identified by its family and its tag.

    Parameters
    ----------
    family : an instance of `SiteFamily`
        The 'type' of the site.
    tag : a hashable python object
        The unique identifier of the site within the site family, typically a
        vector of integers.

    Raises
    ------
    ValueError
        If `tag` is not a proper tag for `family`.

    Notes
    -----
    For convenience, ``family(*tag)`` can be used instead of ``Site(family,
    tag)`` to create a site.

    The parameters of the constructor (see above) are stored as instance
    variables under the same names.  Given a site ``site``, common things to
    query are thus ``site.family``, ``site.tag``, and ``site.pos``.
    """
    __slots__ = ()

    family = property(operator.itemgetter(0),
                      doc="The site family to which the site belongs.")
    tag = property(operator.itemgetter(1), doc="The tag of the site.")


    def __new__(cls, family, tag, _i_know_what_i_do=False):
        if _i_know_what_i_do:
            return tuple.__new__(cls, (family, tag))
        try:
            tag = family.normalize_tag(tag)
        except (TypeError, ValueError) as e:
            msg = 'Tag {0} is not allowed for site family {1}: {2}'
            raise type(e)(msg.format(repr(tag), repr(family), e.args[0]))
        return tuple.__new__(cls, (family, tag))

    def __repr__(self):
        return 'Site({0}, {1})'.format(repr(self.family), repr(self.tag))

    def __str__(self):
        sf = self.family
        return '<Site {0} of {1}>'.format(self.tag, sf.name if sf.name else sf)

    def __getnewargs__(self):
        return (self.family, self.tag, True)

    @property
    def pos(self):
        """Real space position of the site.

        This relies on ``family`` having a ``pos`` method (see `SiteFamily`).
        """
        return self.family.pos(self.tag)


class SiteArray(collections.abc.Sequence):
    """An array of sites, members of a `SiteFamily`.

    Parameters
    ----------
    family : an instance of `SiteFamily`
        The 'type' of the sites.
    tags : a sequence of python objects
        Sequence of unique identifiers of the sites within the
        site array family, typically vectors of integers.

    Raises
    ------
    ValueError
        If ``tags`` are not proper tags for ``family``.

    See Also
    --------
    kwant.system.Site
    """

    def __init__(self, family, tags):
        self.family = family
        try:
            tags = family.normalize_tags(tags)
        except (TypeError, ValueError) as e:
            msg = 'Tags {0} are not allowed for site family {1}: {2}'
            raise type(e)(msg.format(repr(tags), repr(family), e.args[0]))
        self.tags = tags

    def __repr__(self):
        return 'SiteArray({0}, {1})'.format(repr(self.family), repr(self.tags))

    def __str__(self):
        sf = self.family
        return ('<SiteArray {0} of {1}>'
                .format(self.tags, sf.name if sf.name else sf))

    def __len__(self):
        return len(self.tags)

    def __getitem__(self, key):
        if isinstance(key, slice):
            return SiteArray(self.family, self.tags[key])
        else:
            return Site(self.family, self.tags[key])

    def __eq__(self, other):
        if not isinstance(other, SiteArray):
            raise NotImplementedError()
        return self.family == other.family and np.all(self.tags == other.tags)

    def positions(self):
        """Real space position of the site.

        This relies on ``family`` having a ``pos`` method (see `SiteFamily`).
        """
        return self.family.positions(self.tags)


@total_ordering
class SiteFamily:
    """Abstract base class for site families.

    Site families are the 'type' of `Site` objects.  Within a family, individual
    sites are uniquely identified by tags.  Valid tags must be hashable Python
    objects, further details are up to the family.

    Site families must be immutable and fully defined by their initial
    arguments.  They must inherit from this abstract base class and call its
    __init__ function providing it with two arguments: a canonical
    representation and a name.  The canonical representation will be returned as
    the objects representation and must uniquely identify the site family
    instance.  The name is a string used to distinguish otherwise identical site
    families.  It may be empty. ``norbs`` defines the number of orbitals
    on sites associated with this site family; it may be `None`, in which case
    the number of orbitals is not specified.


    All site families must define either 'normalize_tag' or 'normalize_tags',
    which brings a tag (or, in the latter case, a sequence of tags) to the
    standard format for this site family.

    Site families may also implement methods ``pos(tag)`` and
    ``positions(tags)``, which return a vector of realspace coordinates or an
    array of vectors of realspace coordinates of the site(s) belonging to this
    family with the given tag(s). These methods are used in plotting routines.
    ``positions(tags)`` should return an array with shape ``(N, M)`` where
    ``N`` is the length of ``tags``, and ``M`` is the realspace dimension.

    If the ``norbs`` of a site family are provided, and sites of this family
    are used to populate a `~kwant.builder.Builder`, then the associated
    Hamiltonian values must have the correct shape. That is, if a site family
    has ``norbs = 2``, then any on-site terms for sites belonging to this
    family should be 2x2 matrices. Similarly, any hoppings to/from sites
    belonging to this family must have a matrix structure where there are two
    rows/columns. This condition applies equally to Hamiltonian values that
    are given by functions. If this condition is not satisfied, an error will
    be raised.
    """

    def __init__(self, canonical_repr, name, norbs):
        self.canonical_repr = canonical_repr
        self.hash = hash(canonical_repr)
        self.name = name
        if norbs is None:
            warnings.warn("Not specfying norbs is deprecated. Always specify "
                          "norbs when creating site families.",
                          KwantDeprecationWarning, stacklevel=3)
        if norbs is not None:
            if int(norbs) != norbs or norbs <= 0:
                raise ValueError('The norbs parameter must be an integer > 0.')
            norbs = int(norbs)
        self.norbs = norbs

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if (cls.normalize_tag is SiteFamily.normalize_tag
            and cls.normalize_tags is SiteFamily.normalize_tags):
            raise TypeError("Must redefine either 'normalize_tag' or "
                            "'normalize_tags'")

    def __repr__(self):
        return self.canonical_repr

    def __str__(self):
        if self.name:
            msg = '<{0} site family {1}{2}>'
        else:
            msg = '<unnamed {0} site family{2}>'
        orbs = ' with {0} orbitals'.format(self.norbs) if self.norbs else ''
        return msg.format(self.__class__.__name__, self.name, orbs)

    def __hash__(self):
        return self.hash

    def __eq__(self, other):
        try:
            return self.canonical_repr == other.canonical_repr
        except AttributeError:
            return False

    def __ne__(self, other):
        try:
            return self.canonical_repr != other.canonical_repr
        except AttributeError:
            return True

    def __lt__(self, other):
        # If this raises an AttributeError, we were trying
        # to compare it to something non-comparable anyway.
        return self.canonical_repr < other.canonical_repr

    def normalize_tag(self, tag):
        """Return a normalized version of the tag.

        Raises TypeError or ValueError if the tag is not acceptable.
        """
        tag, = self.normalize_tags([tag])
        return tag

    def normalize_tags(self, tags):
        """Return a normalized version of the tags.

        Raises TypeError or ValueError if the tags are not acceptable.
        """
        return np.array([self.normalize_tag(tag) for tag in tags])

    def __call__(self, *tag):
        """
        A convenience function.

        This function allows to write fam(1, 2) instead of Site(fam, (1, 2)).
        """
        # Catch a likely and difficult to find mistake.
        if tag and isinstance(tag[0], tuple):
            raise ValueError('Use site_family(1, 2) instead of '
                             'site_family((1, 2))!')
        return Site(self, tag)


################ Symmetries

class Symmetry(metaclass=abc.ABCMeta):
    """Abstract base class for spatial symmetries.

    Many physical systems possess a discrete spatial symmetry, which results in
    special properties of these systems.  This class is the standard way to
    describe discrete spatial symmetries in Kwant.  An instance of this class
    can be passed to a `Builder` instance at its creation.  The most important
    kind of symmetry is translational symmetry, used to define scattering
    leads.

    Each symmetry has a fundamental domain -- a set of sites and hoppings,
    generating all the possible sites and hoppings upon action of symmetry
    group elements.  A class derived from `Symmetry` has to implement mapping
    of any site or hopping into the fundamental domain, applying a symmetry
    group element to a site or a hopping, and a method `which` to determine the
    group element bringing some site from the fundamental domain to the
    requested one.  Additionally, it has to have a property `num_directions`
    returning the number of independent symmetry group generators (number of
    elementary periods for translational symmetry).

    A ``ValueError`` must be raised by the symmetry class whenever a symmetry
    is used together with sites whose site family is not compatible with it.  A
    typical example of this is when the vector defining a translational
    symmetry is not a lattice vector.

    The type of the domain objects as handled by the methods of this class is
    not specified.  The only requirement is that it must support the unary
    minus operation.  The reference implementation of `to_fd()` is hence
    `self.act(-self.which(a), a, b)`.
    """

    @abc.abstractproperty
    def num_directions(self):
        """Number of elementary periods of the symmetry."""
        pass

    @abc.abstractmethod
    def which(self, site):
        """Calculate the domain of the site.

        Parameters
        ----------
        site : `~kwant.system.Site` or `~kwant.system.SiteArray`

        Returns
        -------
        group_element : tuple or sequence of tuples
            A single tuple if ``site`` is a Site, or a sequence of tuples if
            ``site`` is a SiteArray.  The group element(s) whose action
            on a certain site(s) from the fundamental domain will result
            in the given ``site``.
        """
        pass

    @abc.abstractmethod
    def act(self, element, a, b=None):
        """Act with symmetry group element(s) on site(s) or hopping(s).

        Parameters
        ----------
        element : tuple or sequence of tuples
            Group element(s) with which to act on the provided site(s)
            or hopping(s)
        a, b : `~kwant.system.Site` or `~kwant.system.SiteArray`
            If Site then ``element`` is a single tuple, if SiteArray then
            ``element`` is a single tuple or a sequence of tuples.
            If only ``a`` is provided then ``element`` acts on the site(s)
            of ``a``. If ``b`` is also provided then ``element`` acts
            on the hopping(s) ``(a, b)``.
        """
        pass

    def to_fd(self, a, b=None):
        """Map a site or hopping to the fundamental domain.

        Parameters
        ----------
        a, b : `~kwant.system.Site` or `~kwant.system.SiteArray`

        If ``b`` is None, return a site equivalent to ``a`` within the
        fundamental domain.  Otherwise, return a hopping equivalent to ``(a,
        b)`` but where the first element belongs to the fundamental domain.

        Equivalent to `self.act(-self.which(a), a, b)`.
        """
        return self.act(-self.which(a), a, b)

    def in_fd(self, site):
        """Tell whether ``site`` lies within the fundamental domain.

        Parameters
        ----------
        site : `~kwant.system.Site` or `~kwant.system.SiteArray`

        Returns
        -------
        in_fd : bool or sequence of bool
            single bool if ``site`` is a Site, or a sequence of
            bool if ``site`` is a SiteArray. In the latter case
            we return whether each site in the SiteArray is in
            the fundamental domain.
        """
        if isinstance(site, Site):
            for d in self.which(site):
                if d != 0:
                    return False
            return True
        elif isinstance(site, SiteArray):
            which = self.which(site)
            return np.logical_and.reduce(which != 0, axis=1)
        else:
            raise TypeError("'site' must be a Site or SiteArray")

    @abc.abstractmethod
    def subgroup(self, *generators):
        """Return the subgroup generated by a sequence of group elements."""
        pass

    @abc.abstractmethod
    def has_subgroup(self, other):
        """Test whether `self` has the subgroup `other`...

        or, in other words, whether `other` is a subgroup of `self`.  The
        reason why this is the abstract method (and not `is_subgroup`) is that
        in general it's not possible for a subgroup to know its supergroups.

        """
        pass


class NoSymmetry(Symmetry):
    """A symmetry with a trivial symmetry group."""

    def __eq__(self, other):
        return isinstance(other, NoSymmetry)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return 'NoSymmetry()'

    @property
    def num_directions(self):
        return 0

    periods = ()

    _empty_array = ta.array((), int)

    def which(self, site):
        return self._empty_array

    def act(self, element, a, b=None):
        if element:
            raise ValueError('`element` must be empty for NoSymmetry.')
        return a if b is None else (a, b)

    def to_fd(self, a, b=None):
        return a if b is None else (a, b)

    def in_fd(self, site):
        return True

    def subgroup(self, *generators):
        if any(generators):
            raise ValueError('Generators must be empty for NoSymmetry.')
        return NoSymmetry(generators)

    def has_subgroup(self, other):
        return isinstance(other, NoSymmetry)


################ Systems


class System(metaclass=abc.ABCMeta):
    """Abstract general low-level system.

    Attributes
    ----------
    graph : kwant.graph.CGraph
        The system graph.
    site_ranges : None or sorted sequence of triples of integers
        If provided, encodes ranges of sites that have the same number of
        orbitals. Each triple consists of ``(first_site, norbs, orb_offset)``:
        the first site in the range, the number of orbitals on each site in the
        range, and the offset of the first orbital of the first site in the
        range.  In addition, the final triple should have the form
        ``(graph.num_nodes, 0, tot_norbs)`` where ``tot_norbs`` is the
        total number of orbitals in the system.
    parameters : frozenset of strings
        The names of the parameters on which the system depends. This attribute
        is provisional and may be changed in a future version of Kwant

    Notes
    -----
    The sites of the system are indexed by integers ranging from 0 to
    ``self.graph.num_nodes - 1``.

    Optionally, a class derived from ``System`` can provide a method
    ``pos`` which is assumed to return the real-space position of a site
    given its index.

    Due to the ordering semantics of sequences, and the fact that a given
    ``first_site`` can only appear *at most once* in ``site_ranges``,
    ``site_ranges`` is ordered according to ``first_site``.

    Consecutive elements in ``site_ranges`` are not required to have different
    numbers of orbitals.
    """
    @abc.abstractmethod
    def hamiltonian(self, i, j, *args, params=None):
        """Return the hamiltonian matrix element for sites ``i`` and ``j``.

        If ``i == j``, return the on-site Hamiltonian of site ``i``.

        if ``i != j``, return the hopping between site ``i`` and ``j``.

        Hamiltonians may depend (optionally) on positional and
        keyword arguments.

        Providing positional arguments via 'args' is deprecated,
        instead, provide named parameters as a dictionary via 'params'.
        """
        pass

    @deprecate_args
    def discrete_symmetry(self, args, *, params=None):
        """Return the discrete symmetry of the system.

        The returned object is an instance of
        `~kwant.physics.DiscreteSymmetry`.

        Providing positional arguments via 'args' is deprecated,
        instead, provide named parameters as a dictionary via 'params'.
        """
        # Avoid the circular import.
        from .physics import DiscreteSymmetry
        return DiscreteSymmetry()


    def __str__(self):
        items = [
            # (format, extractor, skip if info not present)
            ('{} sites', self.graph.num_nodes, False),
            ('{} hoppings', self.graph.num_edges, False),
            ('parameters: {}', tuple(self.parameters), True),
        ]
        # Skip some information when it's not present (parameters)
        details = [fmt.format(info) for fmt, info, skip in items
                   if (info or not skip)]
        details = ', and '.join((', '.join(details[:-1]), details[-1]))
        return '<{} with {}>'.format(self.__class__.__name__, details)

    hamiltonian_submatrix = _system.hamiltonian_submatrix


Term = collections.namedtuple(
    "Term",
    ["subgraph", "symmetry_element", "hermitian", "parameters"],
)


class VectorizedSystem(System, metaclass=abc.ABCMeta):
    """Abstract general low-level system with support for vectorization.

    Attributes
    ----------
    symmetry : kwant.system.Symmetry
        The symmetry of the system.
    site_arrays : sequence of SiteArray
        The sites of the system. The family of each site array must have
        ``norbs`` specified.
    site_ranges : Nx3 integer array
        Has 1 row per site array, plus one extra row.  Each row consists
        of ``(first_site, norbs, orb_offset)``: the index of the first
        site in the site array, the number of orbitals on each site in
        the site array, and the offset of the first orbital of the first
        site in the site array.  In addition, the final row has the form
        ``(len(graph.num_nodes), 0, tot_norbs)`` where ``tot_norbs`` is the
        total number of orbitals in the system. Note ``site_ranges``
        is directly computable from ``site_arrays``.
    graph : kwant.graph.CGraph
        The system graph.
    subgraphs : sequence of tuples
        Each subgraph has the form ``((idx1, idx2), (offsets1, offsets2))``
        where ``offsets1`` and ``offsets2`` index sites within the site arrays
        indexed by ``idx1`` and ``idx2``.
    terms : sequence of tuples
        Each tuple has the following structure:
        (subgraph: int, symmetry_element: tuple, hermitian: bool,
         parameters: List(str))
        ``subgraph`` indexes ``subgraphs`` and supplies the to/from sites of this
        term. ``symmetry_element`` is the symmetry group element that should be
        applied to the to-sites of this term.
        ``hermitian`` is ``True`` if the term needs its Hermitian
        conjugate to be added when evaluating the Hamiltonian, and ``parameters``
        contains a list of parameter names used when evaluating this term.
    parameters : frozenset of strings
        The names of the parameters on which the system depends. This attribute
        is provisional and may be changed in a future version of Kwant

    Notes
    -----
    The sites of the system are indexed by integers ranging from 0 to
    ``self.graph.num_nodes - 1``.

    Optionally, a class derived from ``System`` can provide a method
    ``pos`` which is assumed to return the real-space position of a site
    given its index.
    """

    @abc.abstractmethod
    def hamiltonian_term(self, index, selector=slice(None),
                         args=(), params=None):
        """Return the Hamiltonians for hamiltonian term number k.

        Parameters
        ----------
        index : int
            The index of the term to evaluate.
        selector : slice or sequence of int, default: slice(None)
            The elements of the term to evaluate.
        args : tuple
            Positional arguments to the term. (Deprecated)
        params : dict
            Keyword parameters to the term

        Returns
        -------
        hamiltonian : 3d complex array
            Has shape ``(N, P, Q)`` where ``N`` is the number of matrix
            elements in this term (or the number selected by 'selector'
            if provided), ``P`` and ``Q`` are the number of orbitals in the
            'to' and 'from' site arrays associated with this term.

        Providing positional arguments via 'args' is deprecated,
        instead, provide named parameters as a dictionary via 'params'.
        """

    @property
    @lru_cache(1)
    def site_ranges(self):
        site_offsets = np.cumsum([0] + [len(arr) for arr in self.site_arrays])
        norbs = [arr.family.norbs for arr in self.site_arrays] + [0]
        orb_offsets = np.cumsum(
            [0] + [len(arr) * arr.family.norbs for arr in self.site_arrays]
        )
        return np.array([site_offsets, norbs, orb_offsets]).transpose()

    hamiltonian_submatrix = _system.vectorized_hamiltonian_submatrix


class FiniteSystemMixin(metaclass=abc.ABCMeta):
    """Abstract finite low-level system, possibly with leads.

    Attributes
    ----------
    leads : sequence of leads
        Each lead has to provide a method ``selfenergy`` that has
        the same signature as `InfiniteSystem.selfenergy` (without the
        ``self`` parameter), and must have property ``parameters``:
        a collection of strings that name the system parameters (
        though this requirement is provisional and may be removed in
        a future version of Kwant).
        It may also provide ``modes`` that has the
        same signature as `InfiniteSystem.modes` (without the ``self``
        parameter).
    lead_interfaces : sequence of sequences of integers
        Each sub-sequence contains the indices of the system sites
        to which the lead is connected.
    lead_paddings : sequence of sequences of integers
        Each sub-sequence contains the indices of the system sites
        that belong to the lead, and therefore have the same onsite as the lead
        sites, and are connected by the same hoppings as the lead sites.
    parameters : frozenset of strings
        The names of the parameters on which the system depends. This does
        not include the parameters for any leads. This attribute
        is provisional and may be changed in a future version of Kwant

    Notes
    -----
    The length of ``leads`` must be equal to the length of ``lead_interfaces``
    and ``lead_paddings``.

    For lead ``n``, the method leads[n].selfenergy must return a square
    matrix whose size is ``sum(len(self.hamiltonian(site, site)) for
    site in self.lead_interfaces[n])``. The output of ``leads[n].modes``
    has to be a tuple of `~kwant.physics.PropagatingModes`,
    `~kwant.physics.StabilizedModes`.

    Often, the elements of `leads` will be instances of `InfiniteSystem`.  If
    this is the case for lead ``n``, the sites ``lead_interfaces[n]`` match
    the first ``len(lead_interfaces[n])`` sites of the InfiniteSystem.
    """

    @deprecate_args
    def precalculate(self, energy=0, args=(), leads=None,
                     what='modes', *, params=None):
        """
        Precalculate modes or self-energies in the leads.

        Construct a copy of the system, with the lead modes precalculated,
        which may significantly speed up calculations where only the system
        is changing.

        Parameters
        ----------
        energy : float
            Energy at which the modes or self-energies have to be
            evaluated.
        args : sequence
            Additional parameters required for calculating the Hamiltionians.
            Deprecated in favor of 'params' (and mutually exclusive with it).
        leads : sequence of integers or None
            Indices of the leads to be precalculated. If ``None``, all are
            precalculated.
        what : 'modes', 'selfenergy', 'all'
            The quantitity to precompute. 'all' will compute both
            modes and self-energies. Defaults to 'modes'.
        params : dict, optional
            Dictionary of parameter names and their values. Mutually exclusive
            with 'args'.

        Returns
        -------
        syst : FiniteSystem
            A copy of the original system with some leads precalculated.

        Notes
        -----
        If the leads are precalculated at certain `energy` or `args` values,
        they might give wrong results if used to solve the system with
        different parameter values. Use this function with caution.
        """

        if what not in ('modes', 'selfenergy', 'all'):
            raise ValueError("Invalid value of argument 'what': "
                             "{0}".format(what))

        result = copy(self)
        if leads is None:
            leads = list(range(len(self.leads)))
        new_leads = []
        for nr, lead in enumerate(self.leads):
            if nr not in leads:
                new_leads.append(lead)
                continue
            modes, selfenergy = None, None
            if what in ('modes', 'all'):
                modes = lead.modes(energy, args, params=params)
            if what in ('selfenergy', 'all'):
                if modes:
                    selfenergy = modes[1].selfenergy()
                else:
                    selfenergy = lead.selfenergy(energy, args, params=params)
            new_leads.append(PrecalculatedLead(modes, selfenergy))
        result.leads = new_leads
        return result

    @deprecate_args
    def validate_symmetries(self, args=(), *, params=None):
        """Check that the Hamiltonian satisfies discrete symmetries.

        Applies `~kwant.physics.DiscreteSymmetry.validate` to the
        Hamiltonian, see its documentation for details on the return
        format.

        Providing positional arguments via 'args' is deprecated,
        instead, provide named parameters as a dictionary via 'params'.
        """
        symmetries = self.discrete_symmetry(args=args, params=params)
        ham = self.hamiltonian_submatrix(args, sparse=True, params=params)
        return symmetries.validate(ham)


class FiniteSystem(System, FiniteSystemMixin, metaclass=abc.ABCMeta):
    pass


class FiniteVectorizedSystem(VectorizedSystem, FiniteSystemMixin,
                             metaclass=abc.ABCMeta):
    pass


def is_finite(syst):
    return isinstance(syst, (FiniteSystem, FiniteVectorizedSystem))


class InfiniteSystemMixin(metaclass=abc.ABCMeta):

    @deprecate_args
    def modes(self, energy=0, args=(), *, params=None):
        """Return mode decomposition of the lead

        This is a wrapper around `kwant.physics.modes`.  The said
        function is applied to the infinite system at hand.  Any
        discrete symmetries that are declared for the system are
        validated, and, if present, passed on as well.  (Warnings are
        emitted for declared symmetries that are broken.)

        The result of the wrapped function (an instance of
        `~kwant.physics.PropagatingModes` along with an instance of
        `~kwant.physics.StabilizedModes`) is returned unchanged.

        The wave functions of the returned modes are defined over the
        *unit cell* of the system, which corresponds to the degrees of
        freedom on the first ``cell_sites`` sites of the system
        (recall that infinite systems store first the sites in the unit
        cell, then connected sites in the neighboring unit cell).

        Providing positional arguments via 'args' is deprecated,
        instead, provide named parameters as a dictionary via 'params'.
        """
        from . import physics   # Putting this here avoids a circular import.
        ham = self.cell_hamiltonian(args, params=params)
        hop = self.inter_cell_hopping(args, params=params)
        symmetries = self.discrete_symmetry(args, params=params)
        # Check whether each symmetry is broken.
        # If a symmetry is broken, it is ignored in the computation.
        broken = set(symmetries.validate(ham) + symmetries.validate(hop))
        attribute_names = {'Conservation law': 'projectors',
                          'Time reversal': 'time_reversal',
                          'Particle-hole': 'particle-hole',
                          'Chiral': 'chiral'}
        for name in broken:
            warnings.warn('Hamiltonian breaks ' + name +
                          ', ignoring the symmetry in the computation.')
            assert name in attribute_names, 'Inconsistent naming of symmetries'
            setattr(symmetries, attribute_names[name], None)

        shape = ham.shape
        assert len(shape) == 2
        assert shape[0] == shape[1]
        # Subtract energy from the diagonal.
        ham.flat[::ham.shape[0] + 1] -= energy

        # Particle-hole and chiral symmetries only apply at zero energy.
        if energy:
            symmetries.particle_hole = symmetries.chiral = None
        return physics.modes(ham, hop, discrete_symmetry=symmetries)

    @deprecate_args
    def selfenergy(self, energy=0, args=(), *, params=None):
        """Return self-energy of a lead.

        The returned matrix has the shape (s, s), where s is
        ``sum(len(self.hamiltonian(i, i)) for i in range(self.graph.num_nodes -
        self.cell_size))``.

        Providing positional arguments via 'args' is deprecated,
        instead, provide named parameters as a dictionary via 'params'.
        """
        from . import physics   # Putting this here avoids a circular import.
        ham = self.cell_hamiltonian(args, params=params)
        shape = ham.shape
        assert len(shape) == 2
        assert shape[0] == shape[1]
        # Subtract energy from the diagonal.
        ham.flat[::ham.shape[0] + 1] -= energy
        return physics.selfenergy(ham,
                                  self.inter_cell_hopping(args, params=params))

    @deprecate_args
    def validate_symmetries(self, args=(), *, params=None):
        """Check that the Hamiltonian satisfies discrete symmetries.

        Returns `~kwant.physics.DiscreteSymmetry.validate` applied
        to the onsite matrix and the hopping. See its documentation for
        details on the return format.

        Providing positional arguments via 'args' is deprecated,
        instead, provide named parameters as a dictionary via 'params'.
        """
        symmetries = self.discrete_symmetry(args=args, params=params)
        ham = self.cell_hamiltonian(args=args, sparse=True, params=params)
        hop = self.inter_cell_hopping(args=args, sparse=True, params=params)
        broken = set(symmetries.validate(ham) + symmetries.validate(hop))
        return list(broken)


class InfiniteSystem(System, InfiniteSystemMixin, metaclass=abc.ABCMeta):
    """Abstract infinite low-level system.

    An infinite system consists of an infinite series of identical cells.
    Adjacent cells are connected by identical inter-cell hoppings.

    Attributes
    ----------
    cell_size : integer
        The number of sites in a single cell of the system.

    Notes
    -----
    The system graph of an infinite systems contains a single cell, as well as
    the part of the previous cell which is connected to it.  The first
    `cell_size` sites form one complete single cell.  The remaining ``N`` sites
    of the graph (``N`` equals ``graph.num_nodes - cell_size``) belong to the
    previous cell.  They are included so that hoppings between cells can be
    represented.  The N sites of the previous cell correspond to the first
    ``N`` sites of the fully included cell.  When an ``InfiniteSystem`` is used
    as a lead, ``N`` acts also as the number of interface sites to which it
    must be connected.

    The drawing shows three cells of an infinite system.  Each cell consists
    of three sites.  Numbers denote sites which are included into the system
    graph.  Stars denote sites which are not included.  Hoppings are included
    in the graph if and only if they occur between two sites which are part of
    the graph::

            * 2 *
        ... | | | ...
            * 0 3
            |/|/|
            *-1-4

        <-- order of cells

    The numbering of sites in the drawing is one of the two valid ones for that
    infinite system.  The other scheme has the numbers of site 0 and 1
    exchanged, as well as of site 3 and 4.
    """

    @deprecate_args
    def cell_hamiltonian(self, args=(), sparse=False, *, params=None):
        """Hamiltonian of a single cell of the infinite system.

        Providing positional arguments via 'args' is deprecated,
        instead, provide named parameters as a dictionary via 'params'.
        """
        cell_sites = range(self.cell_size)
        return self.hamiltonian_submatrix(args, cell_sites, cell_sites,
                                          sparse=sparse, params=params)

    @deprecate_args
    def inter_cell_hopping(self, args=(), sparse=False, *, params=None):
        """Hopping Hamiltonian between two cells of the infinite system.

        Providing positional arguments via 'args' is deprecated,
        instead, provide named parameters as a dictionary via 'params'.
        """
        cell_sites = range(self.cell_size)
        interface_sites = range(self.cell_size, self.graph.num_nodes)
        return self.hamiltonian_submatrix(args, cell_sites, interface_sites,
                                          sparse=sparse, params=params)


class InfiniteVectorizedSystem(VectorizedSystem, InfiniteSystemMixin,
                               metaclass=abc.ABCMeta):
    """Abstract vectorized infinite low-level system.

    An infinite system consists of an infinite series of identical cells.
    Adjacent cells are connected by identical inter-cell hoppings.

    Attributes
    ----------
    cell_size : integer
        The number of sites in a single cell of the system.

    Notes
    -----
    Unlike `~kwant.system.InfiniteSystem`, vectorized infinite systems do
    not explicitly store the sites in the previous unit cell; only the
    sites in the fundamental domain are stored. Nevertheless, the
    SiteArrays of `~kwant.system.InfiniteVectorizedSystem` are ordered
    in an analogous way, in order to facilitate the representation of
    inter-cell hoppings. The ordering is as follows. The *interface sites*
    of a unit cell are the sites that have hoppings to the *next* unit cell
    (along the symmetry direction). Interface sites are always in different
    SiteArrays than non-interface sites, i.e. the sites in a given SiteArray
    are either all interface sites, or all non-interface sites.
    The SiteArrays consisting of interface sites always appear *before* the
    SiteArrays consisting of non-interface sites in ``self.site_arrays``.
    This is backwards compatible with `kwant.system.InfiniteSystem`.

    For backwards compatibility, `~kwant.system.InfiniteVectorizedSystem`
    maintains a ``graph``, that includes nodes for the sites
    in the previous unit cell.
    """
    cell_hamiltonian = _system.vectorized_cell_hamiltonian
    inter_cell_hopping = _system.vectorized_inter_cell_hopping

    def hamiltonian_submatrix(self, args=(), sparse=False,
                              return_norb=False, *, params=None):
        raise ValueError(
            "'hamiltonian_submatrix' is not meaningful for infinite"
            "systems. Use 'cell_hamiltonian' or 'inter_cell_hopping."
        )


def is_infinite(syst):
    return isinstance(syst, (InfiniteSystem, InfiniteVectorizedSystem))


def is_vectorized(syst):
    return isinstance(syst, (FiniteVectorizedSystem, InfiniteVectorizedSystem))


def is_selfenergy_lead(lead):
    return hasattr(lead, "selfenergy") and not hasattr(lead, "modes")


def _normalize_matrix_blocks(blocks, expected_shape, *, calling_function=None):
    """Normalize a sequence of matrices into a single 3D numpy array

    Parameters
    ----------
    blocks : sequence of complex array-like
    expected_shape : (int, int, int)
    calling_function : callable (optional)
        The function that produced 'blocks'. If provided, used to give
        a more helpful error message if 'blocks' is not of the correct shape.
    """
    try:
        blocks = np.asarray(blocks, dtype=complex)
    except TypeError:
        raise ValueError(
            "Matrix elements declared with incompatible shapes."
        ) from None
    original_shape = blocks.shape
    was_broadcast = True  # Did the shape get broadcasted to a more general one?
    if len(blocks.shape) == 0:  # scalar → broadcast to vector of 1x1 matrices
        blocks = np.tile(blocks, (expected_shape[0], 1, 1))
    elif len(blocks.shape) == 1:  # vector → interpret as vector of 1x1 matrices
        blocks = blocks.reshape(-1, 1, 1)
    elif len(blocks.shape) == 2:  # matrix → broadcast to vector of matrices
        blocks = np.tile(blocks, (expected_shape[0], 1, 1))
    else:
        was_broadcast = False

    if blocks.shape != expected_shape:
        msg = (
            "Expected values of shape {}, but received values of shape {}"
                .format(expected_shape, blocks.shape),
            "(broadcasted from shape {})".format(original_shape)
                if was_broadcast else "",
            "when evaluating {}".format(calling_function.__name__)
                if callable(calling_function) else "",
        )
        raise ValueError(" ".join(msg))

    return blocks



class PrecalculatedLead:
    def __init__(self, modes=None, selfenergy=None):
        """A general lead defined by its self energy.

        Parameters
        ----------
        modes : (kwant.physics.PropagatingModes, kwant.physics.StabilizedModes)
            Modes of the lead.
        selfenergy : numpy array
            Lead self-energy.

        Notes
        -----
        At least one of ``modes`` and ``selfenergy`` must be provided.
        """
        if modes is None and selfenergy is None:
            raise ValueError("No precalculated values provided.")
        self._modes = modes
        self._selfenergy = selfenergy
        # Modes/Self-energy have already been evaluated, so there
        # is no parametric dependence anymore
        self.parameters = frozenset()

    @deprecate_args
    def modes(self, energy=0, args=(), *, params=None):
        if self._modes is not None:
            return self._modes
        else:
            raise ValueError("No precalculated modes were provided. "
                             "Consider using precalculate() with "
                             "what='modes' or what='all'")

    @deprecate_args
    def selfenergy(self, energy=0, args=(), *, params=None):
        if self._selfenergy is not None:
            return self._selfenergy
        else:
            raise ValueError("No precalculated selfenergy was provided. "
                             "Consider using precalculate() with "
                             "what='selfenergy' or what='all'")

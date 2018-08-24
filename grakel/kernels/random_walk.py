"""RW-ker. as in :cite:`kashima2003marginalized`, :cite:`gartner2003graph`."""
# Author: Ioannis Siglidis <y.siglidis@gmail.com>
# License: BSD 3 clause
import collections
import warnings

import numpy as np

from itertools import product

from numpy import ComplexWarning
from numpy.linalg import inv
from numpy.linalg import eig
from scipy.linalg import expm
from scipy.sparse.linalg import cg
from scipy.sparse.linalg import LinearOperator

from grakel.kernels import Kernel
from grakel.graph import Graph

# Python 2/3 cross-compatibility import
from builtins import range


class RandomWalk(Kernel):
    """The random walk kernel class.

    See :cite:`kashima2003marginalized`, :cite:`gartner2003graph`
    and :cite:`vishwanathan2006fast`.

    Parameters
    ----------
    lambda : float
        A lambda factor concerning summation.

    method_type : str, valid_values={"baseline", "fast"}
        The method to use for calculating random walk kernel:
            + "baseline" *Complexity*: :math:`O(|V|^6)`
              (see :cite:`kashima2003marginalized`, :cite:`gartner2003graph`)
            + "fast" *Complexity*: :math:`O((|E|+|V|)|V||M|)`
              (see :cite:`vishwanathan2006fast`)

    kernel_type : str, valid_values={"geometric", "exponential"}
        Defines how inner summation will be applied.

    p : int or None
        If initialised defines the number of steps.

    Attributes
    ----------
    lamda : float, default=0.1
        A lambda factor concerning summation.

    kernel_type : str, valid_values={"geometric", "exponential"},
    default="geometric"
        Defines how inner summation will be applied.

    method_type : str valid_values={"baseline", "fast"},
    default="fast"
        The method to use for calculating random walk kernel:
            + "baseline" *Complexity*: :math:`O(|V|^6)`
              (see :cite:`kashima2003marginalized`, :cite:`gartner2003graph`)
            + "fast" *Complexity*: :math:`O((|E|+|V|)|V||M|)`
              (see :cite:`vishwanathan2006fast`)

    p : int or None
        If initialised defines the number of steps.

    """

    _graph_format = "adjacency"

    def __init__(self, n_jobs=None,
                 normalize=False, verbose=False,
                 lamda=0.1, method_type="fast",
                 kernel_type="geometric", p=None):
        """Initialise a random_walk kernel."""
        # setup valid parameters and initialise from parent
        super(RandomWalk, self).__init__(
            n_jobs=n_jobs, normalize=normalize, verbose=verbose)

        # Ignores ComplexWarning as it does not signify anything problematic
        warnings.filterwarnings('ignore', category=ComplexWarning)

        # Setup method type and define operation.
        self.method_type = method_type
        self.kernel_type = kernel_type
        self.p = p
        self.lamda = lamda
        self.initialized_.update({"method_type": False, "kernel_type": False,
                                  "p": False, "lamda": False})

    def initialize_(self):
        """Initialize all transformer arguments, needing initialization."""
        super(RandomWalk, self).initialize_()

        if not self.initialized_["method_type"]:
            # Setup method type and define operation.
            if self.method_type == "fast":
                def invert(w, v):
                    # Spectral Decomposition if adjacency matrix is symmetric
                    return (np.real(np.sum(v, axis=0)), np.real(w))

                def add_input(x):
                    return invert(*eig(x))

                self._add_input = add_input
            elif self.method_type == "baseline":
                def add_input(x):
                    return x
                self._add_input = add_input
            else:
                raise ValueError('unsupported method_type')
            self.initialized_["method_type"] = True

        if not self.initialized_["kernel_type"]:
            if self.kernel_type not in ["geometric", "exponential"]:
                raise ValueError('unsupported kernel type: either "geometric" '
                                 'or "exponential"')

        if not self.initialized_["p"]:
            if self.p is not None:
                if type(self.p) is int and self.p > 0:
                    if self.kernel_type == "geometric":
                        self._mu = [1]
                        fact = 1
                        power = 1
                        for k in range(1, self.p + 1):
                            fact *= k
                            power *= self.lamda
                            self._mu.append(fact/power)
                    else:
                        self._mu = [1]
                        power = 1
                        for k in range(1, self.p + 1):
                            power *= self.lamda
                            self._mu.append(power)
                else:
                    raise TypeError('p must be a positive integer bigger than '
                                    'zero or nonetype')
                self.initialized_["kernel_type"] = True

        if not self.initialized_["lamda"]:
            if self.lamda <= 0:
                raise TypeError('lambda must be positive bigger than equal')
            elif self.lamda > 0.5 and self.p is None:
                warnings.warn('ranodm-walk series may fail to converge')
            self.initialized_["lamda"] = True

    def parse_input(self, X):
        """Parse and create features for random_walk kernel.

        Parameters
        ----------
        X : iterable
            For the input to pass the test, we must have:
            Each element must be an iterable with at most three features and at
            least one. The first that is obligatory is a valid graph structure
            (adjacency matrix or edge_dictionary) while the second is
            node_labels and the third edge_labels (that correspond to the given
            graph format). A valid input also consists of graph type objects.

        Returns
        -------
        out : list
            The extracted adjacency matrices for any given input.

        """
        if not isinstance(X, collections.Iterable):
            raise TypeError('input must be an iterable\n')
        else:
            i = 0
            out = list()
            for (idx, x) in enumerate(iter(X)):
                is_iter = isinstance(x, collections.Iterable)
                if is_iter:
                    x = list(x)
                if is_iter and len(x) in [0, 1, 2, 3]:
                    if len(x) == 0:
                        warnings.warn('Ignoring empty element' +
                                      ' on index: '+str(idx))
                        continue
                    else:
                        A = Graph(x[0], {}, {},
                                  self._graph_format).get_adjacency_matrix()
                elif type(x) is Graph:
                    A = x.get_adjacency_matrix()
                else:
                    raise TypeError('each element of X must be either a ' +
                                    'graph or an iterable with at least 1 ' +
                                    'and at most 3 elements\n')
                i += 1
                out.append(self._add_input(A))

            if i == 0:
                raise ValueError('parsed input is empty')

            return out

    def pairwise_operation(self, X, Y):
        """Calculate the random walk kernel.

        Fast:
        Spectral demoposition algorithm as presented in
        :cite:`vishwanathan2006fast` p.13, s.4.4, with
        complexity of :math:`O((|E|+|V|)|E||V|^2)` for graphs witout labels.

        Baseline:
        Algorithm presented in :cite:`kashima2003marginalized`,
        :cite:`gartner2003graph` with complexity of :math:`O(|V|^6)`

        Parameters
        ----------
        X, Y : Objects
            Objects as produced from parse_input.

        Returns
        -------
        kernel : number
            The kernel value.

        """
        if self.method_type == "baseline":
            # calculate the product graph
            XY = np.kron(X, Y)

            # algorithm presented in
            # [Kashima et al., 2003; Gartner et al., 2003]
            # complexity of O(|V|^6)

            # XY is a square matrix
            s = XY.shape[0]

            if self.p is not None:
                P = np.eye(XY.shape[0])
                S = self._mu[0] * P
                for k in self._mu[1:]:
                    P *= XY
                    S += k*P
            else:
                if self.kernel_type == "geometric":
                    S = inv(np.identity(s) - self.lamda*XY).T
                elif self.kernel_type == "exponential":
                    S = expm(self.lamda*XY).T

            return np.sum(S)
        elif self.method_type == "fast":
            # Spectral demoposition algorithm as presented in
            # [Vishwanathan et al., 2006] p.13, s.4.4, with
            # complexity of O((|E|+|V|)|E||V|^2) for graphs
            # witout labels

            # calculate kernel
            qi_Pi, wi = X
            qj_Pj, wj = Y

            # calculate flanking factor
            ff = np.expand_dims(np.kron(qi_Pi, qj_Pj), axis=0)

            # calculate D based on the method
            Dij = np.kron(wi, wj)
            if self.p is not None:
                D = np.ones(shape=(Dij.shape[0],))
                S = self._mu[0] * D
                for k in self._mu[1:]:
                    D *= Dij
                    S += k*D

                S = np.diagflat(S)
            else:
                if self.kernel_type == "geometric":
                    S = np.diagflat(1/(1-self.lamda*Dij))
                elif self.kernel_type == "exponential":
                    S = np.diagflat(np.exp(self.lamda*Dij))

            return ff.dot(S).dot(ff.T)


class RandomWalkLabeled(RandomWalk):
    """The labeled random walk kernel class.

    See :cite:`kashima2003marginalized`, :cite:`gartner2003graph`
    and :cite:`vishwanathan2006fast`.

    Parameters
    ----------
    lambda : float
        A lambda factor concerning summation.

    method_type : str, valid_values={"baseline", "fast"}
        The method to use for calculating random walk kernel:
            + "baseline" *Complexity*: :math:`O(|V|^6)`
              (see :cite:`kashima2003marginalized`,
              :cite:`gartner2003graph`)
            + "fast" *Complexity*: :math:`O((|E|+|V|)|V||M|)`
              (see :cite:`vishwanathan2006fast`)

    kernel_type : str, valid_values={"geometric", "exponential"}
        Defines how inner summation will be applied.

    p : int, optional
        If initialised defines the number of steps.

    Attributes
    ----------
    _lamda : float, default=0.1
        A lambda factor concerning summation.

    _kernel_type : str, valid_values={"geometric", "exponential"},
    default="geometric"
        Defines how inner summation will be applied.

    _method_type : str valid_values={"baseline", "fast"},
    default="fast"
        The method to use for calculating random walk kernel:
            + "baseline" *Complexity*: :math:`O(|V|^6)`
              (see :cite:`kashima2003marginalized`,
              :cite:`gartner2003graph`)
            + "fast" *Complexity*: :math:`O((|E|+|V|)|V||M|)`
              (see :cite:`vishwanathan2006fast`)

    _p : int, default=1
        If not -1, the number of steps of the random walk kernel.

    """

    _graph_format = "adjacency"

    def __init__(self, n_jobs=None,
                 normalize=False, verbose=False,
                 lamda=0.1, method_type="fast",
                 kernel_type="geometric", p=None):
        """Initialise a labeled random_walk kernel."""
        # Initialise from parent
        super(RandomWalkLabeled, self).__init__(
            n_jobs=n_jobs, normalize=normalize, verbose=verbose,
            lamda=lamda, method_type=method_type, kernel_type=kernel_type,
            p=p)

    def parse_input(self, X):
        """Parse and create features for graphlet_sampling kernel.

        Parameters
        ----------
        X : iterable
            For the input to pass the test, we must have:
            Each element must be an iterable with at most three features and at
            least one. The first that is obligatory is a valid graph structure
            (adjacency matrix or edge_dictionary) while the second is
            node_labels and the third edge_labels (that correspond to the given
            graph format). A valid input also consists of graph type objects.

        Returns
        -------
        out : list
            The extracted adjacency matrices for any given input.

        """
        if not isinstance(X, collections.Iterable):
            raise TypeError('input must be an iterable\n')
        else:
            i = 0
            proc = list()
            for (idx, x) in enumerate(iter(X)):
                is_iter = isinstance(x, collections.Iterable)
                if is_iter:
                    x = list(x)
                if is_iter and len(x) in [1, 2, 3]:
                    if len(x) == 0:
                        warnings.warn('Ignoring empty element' +
                                      ' on index: '+str(idx))
                        continue
                    else:
                        x = Graph(x[0], x[1], {}, self._graph_format)
                elif type(x) is not Graph:
                    raise TypeError('each element of X must be either a ' +
                                    'graph or an iterable with at least 2 ' +
                                    'and at most 3 elements\n')
                i += 1
                x.desired_format("adjacency")
                Ax = x.get_adjacency_matrix()
                Lx = x.get_labels(purpose="adjacency")
                Lx = [Lx[idx] for idx in range(Ax.shape[0])]
                proc.append((Ax, Lx, Ax.shape[0]))

            out = list()
            for Ax, Lx, s in proc:
                amss = dict()
                labels = set(Lx)
                Lx = np.array(Lx)
                for t in product(labels, labels):
                    selector = np.matmul(np.expand_dims(Lx == t[0], axis=0),
                                         np.expand_dims(Lx == t[1], axis=1))
                    amss[t] = Ax * selector
                out.append((amss, s))

            if i == 0:
                raise ValueError('parsed input is empty')

            return out

    def pairwise_operation(self, X, Y):
        """Calculate the labeled random walk kernel.

        Fast:
        Spectral demoposition algorithm as presented in
        :cite:`vishwanathan2006fast` p.13, s.4.4, with
        complexity of :math:`O((|E|+|V|)|E||V|^2)` for graphs witout labels.

        Baseline:
        Algorithm presented in :cite:`kashima2003marginalized`,
        :cite:`gartner2003graph` with complexity of :math:`O(|V|^6)`

        Parameters
        ----------
        X, Y : tuples
            Tuples of adjacency matrices and labels.

        Returns
        -------
        kernel : number
            The kernel value.

        """
        X, xs = X
        Y, ys = Y
        ck = set(X.keys()) & (set(Y.keys()))

        if len(ck) == 0:
            return .0
        mn = xs * ys

        if self.kernel_type == "exponential" or self.method_type == "baseline" or self.p is not None:
            # Claculate Kronecker product matrix
            XY = np.zeros(shape=(mn, mn))
            for k in ck:
                XY += np.kron(X[k], Y[k])

            # XY is a square matrix
            s = XY.shape[0]

            if self.p is not None:
                P = np.eye(XY.shape[0])
                S = self._mu[0] * P
                for k in self._mu[1:]:
                    P *= XY
                    S += k*P
            elif self.kernel_type == "exponential":
                S = expm(self.lamda*XY).T
            elif self.kernel_type == "geometric":
                # Baseline Algorithm as presented in
                # [Vishwanathan et al., 2006]
                Id = np.identity(s)
                S = inv(Id - self.lamda*XY).T

            return np.sum(S)
        elif self.method_type == "fast" and self.kernel_type == "geometric":
            # Conjugate Gradient Method as presented in
            # [Vishwanathan et al., 2006] p.13, s.4.
            AxAy = [(X[k], Y[k]) for k in ck]

            def lsf(x, lamda):
                y = 0
                xm = x.reshape((xs, ys))
                for Ax, Ay in AxAy:
                    y += np.reshape(np.matmul(np.matmul(Ax, xm), Ay), (mn,))
                return x - self.lamda * y

            # A*x=b
            A = LinearOperator((mn, mn), matvec=lambda x: lsf(x, self.lamda))
            b = np.ones(mn)
            x_sol, _ = cg(A, b, tol=1.0e-6, maxiter=200)
            return np.sum(x_sol)

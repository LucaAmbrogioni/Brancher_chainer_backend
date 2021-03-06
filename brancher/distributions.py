"""
Distributions
---------
Module description
"""
from abc import ABC, abstractmethod
from collections.abc import Iterable
import copy

import chainer
import chainer.functions as F
import numpy as np
from scipy.special import binom

from brancher.utilities import broadcast_and_squeeze
from brancher.utilities import sum_data_dimensions
from brancher.utilities import get_diagonal
from brancher.utilities import broadcast_parent_values

# TODO: This module is messy with ad hoc solutions for every distribution. You need to make everything more standardized.

# TODO: You need to implement a consistent broadcasting strategy for univariate, multivariate and tensor distributions.

# TODO: Remove "number samples" input


class Distribution(ABC):
    """
    Summary
    """
    @abstractmethod
    def calculate_log_probability(self, *parameters):
        pass

    @abstractmethod
    def get_sample(self, *parameters):
        pass


## Implicit distributions ##
class ImplicitDistribution(Distribution):

    def calculate_log_probability(self, x, **parameters):
        return np.zeros((1, 1)).astype("float32") #TODO: Implement some checks here


# class EmpiricalDistribution(ImplicitDistribution):
#     """
#     Summary
#     """
#     def get_sample(self, dataset, indices, number_samples):
#         """
#         One line description
#
#         Parameters
#         ----------
#         Returns
#         -------
#         Without replacement
#         """
#         if not indices:
#             if isinstance(dataset, chainer.Variable):
#                 dataset_size = dataset.shape[1]
#             else:
#                 dataset_size = len(dataset)
#             if dataset_size < self.batch_size:
#                 raise ValueError("It is impossible to have more samples than the size of the dataset without replacement")
#             indices = np.random.choice(range(dataset_size), size=self.batch_size, replace=False)
#
#         if isinstance(dataset, chainer.Variable):
#             sample = dataset[:, indices, :]
#         else:
#             sample = list(np.array(dataset)[indices]) #TODO: clean up
#         return sample


class EmpiricalDistribution(ImplicitDistribution):
    """
    Summary
    """
    def get_sample(self, dataset, indices, number_samples, weights=None):
        """
        One line description

        Parameters
        ----------
        Returns
        -------
        Without replacement
        """
        if not indices:
            if weights:
                p = np.array(weights).astype("float64")
                p = p/np.sum(p)
            else:
                p = None
            if isinstance(dataset, chainer.Variable):
                if self.is_observed:
                    dataset_size = dataset.shape[1]
                else:
                    dataset_size = dataset.shape[2]
            else:
                dataset_size = len(dataset)
            if dataset_size < self.batch_size:
                raise ValueError("It is impossible to have more samples than the size of the dataset without replacement")
            if isinstance(dataset, Iterable): # TODO: This is for allowing discrete data, temporary?
                indices = np.random.choice(range(dataset_size), size=self.batch_size, replace=False, p=p)
            else:
                indices = [np.random.choice(range(dataset_size), size=self.batch_size, replace=False, p=p)
                           for _ in range(number_samples)]

        if isinstance(dataset, chainer.Variable):
            if isinstance(indices, list) and isinstance(indices[0], np.ndarray):
                if self.is_observed:
                    sample = F.concat([F.expand_dims(dataset[n, k, :], axis=0) for n, k in enumerate(indices)], axis=0)
                else:
                    sample = F.concat([F.expand_dims(dataset[n, :, k, :], axis=0) for n, k in enumerate(indices)], axis=0)

            elif isinstance(indices, list) and isinstance(indices[0], (int, np.int32, np.int64)):
                if self.is_observed:
                    sample = dataset[:, indices, :]
                else:
                    sample = dataset[:, :, indices, :]
            else:
                raise IndexError("The indices of an empirical variable should be either a list of integers or a list of arrays")
        else:
            sample = list(np.array(dataset)[indices]) # TODO: This is for allowing discrete data, temporary? For julia
        return sample


## Unnormalized distributions ##
class UnnormalizedDistribution(Distribution):
    pass


class TruncatedDistribution(UnnormalizedDistribution): #TODO: To be removed after refactoring, work in progress
    def __init__(self, base_distribution, truncation_rule):
        self.base_distribution = base_distribution
        self.truncation_rule = truncation_rule

    def _reject_samples(self, samples, remaining_indices):
        sample_list, sample_indices = zip(*[(F.expand_dims(s, axis=0), index)
                                            for index, s in enumerate(samples) if self.truncation_rule(s.data)])
        return sample_list, [remaining_indices[index] for index in sample_indices]

    def calculate_log_probability(self, x, **kwargs):
        return self.base_distribution.calculate_log_probability(x, **kwargs)

    def get_sample(self, number_samples, max_depth=20, **kwargs):
        total_sampled_indices = set()
        while not total_sampled_indices:
            truncated_samples = {}
            original_range = range(number_samples)
            remaining_indices = range(number_samples)
            original_input_parents = kwargs
            iteration_index = 0
            while total_sampled_indices != set(original_range) and iteration_index < max_depth:
                input_parents = {parent: value[remaining_indices, :] if value.shape[0] == number_samples else value
                                 for parent, value in original_input_parents.items()}
                try:
                    if iteration_index < max_depth:
                        sample_list, sample_indices = self._reject_samples(self.base_distribution.get_sample(number_samples=number_samples,
                                                                                                             **input_parents), remaining_indices)
                        remaining_indices = [index for index in remaining_indices if index not in total_sampled_indices]
                        truncated_samples.update({index: sample for index, sample in zip(sample_indices, sample_list)})
                        total_sampled_indices.update(set(sample_indices))
                        iteration_index += 1
                    else:
                        pass
                except ValueError:
                    iteration_index += 1
                    pass
        return F.concat([value for (key, value) in sorted(truncated_samples.items())], axis=0)


## Univariate distributions ##
class UnivariateDistribution(Distribution):
    pass


class NormalDistribution(UnivariateDistribution):
    """
    Summary
    """
    def calculate_log_probability(self, x, mu, sigma):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        x, mu, sigma = broadcast_and_squeeze(x, mu, sigma)
        log_probability = -0.5*F.log(2*np.pi*sigma**2) - 0.5*(x-mu)**2/(sigma**2)
        return sum_data_dimensions(log_probability)

    def get_sample(self, mu, sigma, number_samples):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        mean, var = broadcast_and_squeeze(mu, sigma)
        sample = mean + sigma*np.random.normal(0, 1, size=mean.shape)
        return sample


class CauchyDistribution(UnivariateDistribution):
    """
    Summary
    """
    def calculate_log_probability(self, x, mu, sigma):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        x, mu, sigma = broadcast_and_squeeze(x, mu, sigma)
        log_probability = -F.log(1 + (x-mu)**2/sigma**2)
        return sum_data_dimensions(log_probability)

    def get_sample(self, mu, sigma, number_samples):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        mu, sigma = broadcast_and_squeeze(mu, sigma)
        sample = mu + sigma*F.tan(np.pi*np.random.uniform(0, 1, size=mu.shape).astype(np.float32))
        return sample


class LogNormalDistribution(UnivariateDistribution):
    """
    Summary
    """
    def calculate_log_probability(self, x, mu, sigma):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        x, mu, sigma = broadcast_and_squeeze(x, mu, sigma)
        log_probability = -0.5*np.log(2*np.pi) - F.log(x) - F.log(sigma) - 0.5*(F.log(x)-mu)**2/(sigma**2)
        return sum_data_dimensions(log_probability)

    def get_sample(self, mu, sigma, number_samples):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        mu, sigma = broadcast_and_squeeze(mu, sigma)
        log_sample = mu + sigma*np.random.normal(0,1,size=mu.shape)
        return F.exp(log_sample)


class LogitNormalDistribution(UnivariateDistribution):
    """
    Summary
    """
    def calculate_log_probability(self, x, mu, sigma):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        def logit(p):
            return F.log(p) - F.log(1-p)
        x, mu, sigma = broadcast_and_squeeze(x, mu, sigma)
        log_probability = -0.5*np.log(2*np.pi) - F.log(x) - F.log(1-x) - F.log(sigma) - 0.5*(logit(x)-mu)**2/(sigma**2)
        return sum_data_dimensions(log_probability)

    def get_sample(self, mu, sigma, number_samples):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        mu, sigma = broadcast_and_squeeze(mu, sigma)
        logit_sample = mu + sigma*np.random.normal(0, 1, size=mu.shape)
        return F.sigmoid(logit_sample)


class BinomialDistribution(UnivariateDistribution):
    """
    Summary
    """
    def calculate_log_probability(self, x, n, p):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        x, n, p = broadcast_and_squeeze(x, n, p)
        x, n = x.data, n.data
        log_probability = np.log(binom(n, x)) + x*F.log(p) + (n-x)*F.log(1-p)
        return sum_data_dimensions(log_probability)

    def get_sample(self, n, p, number_samples):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        n, p = broadcast_and_squeeze(n, p)
        binomial_sample = np.random.binomial(n.data, p.data) #TODO: Not reparametrizable (Gumbel?)
        return chainer.Variable(binomial_sample.astype("int32"))


class LogitBinomialDistribution(UnivariateDistribution):
    """
    Summary
    """
    def calculate_log_probability(self, x, n, z):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        x, n, z = broadcast_and_squeeze(x, n, z)
        x, n = x.data, n.data
        alpha = F.relu(-z).data
        beta = F.relu(z).data
        success_term = x*alpha - x*F.log(np.exp(alpha) + F.exp(alpha-z))
        failure_term = (n-x)*beta - (n-x)*F.log(np.exp(beta) + F.exp(beta+z))
        log_probability = np.log(binom(n, x)) + success_term + failure_term
        return sum_data_dimensions(log_probability)

    def get_sample(self, n, z, number_samples):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        n, z = broadcast_and_squeeze(n, z)
        binomial_sample = np.random.binomial(n.data, F.sigmoid(z).data) #TODO: Not reparametrizable (Gumbel?)
        return chainer.Variable(binomial_sample.astype("int32"))


## Multivariate distributions ##
class MultivariateDistribution(Distribution):
    pass


class CholeskyMultivariateNormal(MultivariateDistribution): #TODO: This needs to be finished
    """
    Summary
    """

    def calculate_log_probability(self, x, mu, chol_cov):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        log_det = 2*F.sum(F.log(get_diagonal(chol_cov)), axis=2)
        whitened_input = F.matmul(F.transpose(chol_cov, axes=(1, 2, 4, 3)), x)
        exponent = F.sum(whitened_input**2, axis=2)
        log_probability = -0.5*np.log(2*np.pi) -0.5*log_det -0.5*exponent
        return sum_data_dimensions(log_probability)

    def get_sample(self, mu, chol_cov, number_samples):
            """
            One line description

            Parameters
            ----------

            Returns
            -------
            """
            random_vector = np.random.normal(0,1,size=mu.shape).astype("float32")
            return mu + F.matmul(chol_cov, random_vector)

class CategoricalDistribution(MultivariateDistribution):
    """
    Summary
    """
    def calculate_log_probability(self, x, p):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        x, p = broadcast_and_squeeze(x, p)
        x = x.data
        log_probability = F.sum(x*F.log(p), axis=2)
        return sum_data_dimensions(log_probability)

    def get_sample(self, p, number_samples):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        p_values = p.data
        p_shape = p_values.shape
        sample = np.swapaxes(np.array([[np.random.multinomial(1, p_values[j, k, :])
                                        for j in range(p_shape[0])]
                                       for k in range(p_shape[1])]), axis1=0, axis2=1)
        return chainer.Variable(sample.astype("int32"))


class SoftmaxCategoricalDistribution(MultivariateDistribution): #TODO: Work in progress!!!
    """
        Summary
        """

    def calculate_log_probability(self, x, z):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        reshaped_dict, n_samples, n_datapoints = broadcast_parent_values({"x": x, "z": z})
        labels = np.reshape(reshaped_dict["x"].data, newshape=(n_samples*n_datapoints, 1))
        log_probability = -F.softmax_cross_entropy(reshaped_dict["z"], labels, reduce="no")
        log_probability = F.reshape(log_probability, shape=(n_samples, n_datapoints))
        return log_probability

    def get_sample(self, z, number_samples):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        # import matplotlib.pyplot as plt
        # [plt.plot(z.data[k, 0, :, 0]) for k in range(10)] #TODO: Work in progress
        p_values = F.softmax(z, axis=2).data
        p_shape = p_values.shape
        p_values = np.reshape(p_values.astype("float64"), newshape=p_shape[:2] + tuple([np.prod(p_shape[2:])])) #TODO: This should go in a more general class (Future refactoring)
        sample = np.swapaxes(np.array([[np.random.multinomial(1, p_values[j, k, :]/np.sum(p_values[j, k, :]))
                                        for j in range(p_shape[0])]
                                       for k in range(p_shape[1])]), axis1=0, axis2=1)
        sample = np.reshape(sample, newshape=p_shape)
        return chainer.Variable(sample.astype("int32"))


class ConcreteDistribution(MultivariateDistribution):
    """
    Summary
    """
    def calculate_log_probability(self, x, p, tau):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        dim = p.shape[2]
        #p, tau = F.broadcast(p, tau)
        normalization = F.log(F.sum(p*x**(-tau-1), axis=2))
        log_probability = (F.sum(np.log(dim + 1) + (dim - 1)*F.log(tau), axis=2) + F.sum(F.log(p) + (-tau + 1)*F.log(x), axis=2)
                           - dim*normalization)
        return log_probability

    def get_sample(self, p, tau, number_samples):
        """
        One line description

        Parameters
        ----------

        Returns
        -------
        """
        p, tau = F.broadcast(p, tau)
        gumbel_sample = np.random.gumbel(0, 1, size=p.shape)
        return F.softmax((F.log(p) + gumbel_sample)/tau, axis=2)


# StochasticProcesses #
# class StochasticProcesses(MultivariateDistribution):
#     pass
#
#
# class DiffusionProcess(StochasticProcesses): #TODO: This needs to be finished
#     """
#     Summary
#     """
#     def __init__(self, drift_function, diffusion_function, time_spacing):
#         self.drift = drift_function
#         self.diffusion = diffusion_function
#         self.time_spacing = time_spacing
#
#     def calculate_log_probability(self, time_series):
#         """
#         One line description
#
#         Parameters
#         ----------
#
#         Returns
#         -------
#         """
#         pass
#
#     def _get_sample(self, p, tau, number_samples):
#         """
#         One line description
#
#         Parameters
#         ----------
#         mu : numeric
#         sigma : numeric
#         number_samples : int
#
#         Returns
#         -------
#         sample : type
#         """
#         pass

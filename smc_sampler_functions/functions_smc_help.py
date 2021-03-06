# file with the functions that we use in the smc sampler
import numpy as np
import warnings
import sys
from statsmodels.regression.quantile_regression import QuantReg

import sys
from help import resampling
from help.hilbert import brutehilbertsort
from help.resampling import resampling_inverse_transform

from matplotlib import pyplot as plt
from matplotlib.ticker import MaxNLocator
from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D
from scipy.stats import chi2

class sequence_distributions(object):
    """
    class that returns gradient of log density and the log density
    """
    def __init__(self, parameters, priordistribution, targetdistribution):
        """
        parameters, dict with parameters for target dist
        priordist : dict with 'logdensity' and 'gradlogdensity', has to be callable
        targetdist : dict with 'logdensity' and 'gradlogdensity', has to be callable
        """
        self.parameters = parameters
        self.priorlogdens = priordistribution['logdensity']
        self.priorsampler = priordistribution['priorsampler']
        self.targetlogdens = targetdistribution['logdensity']
        self.priorgradlogdens = priordistribution['gradlogdensity']
        self.targetgradlogdens = targetdistribution['gradlogdensity']
        self.target_name = targetdistribution['target_name']
        
        assert callable(self.priorlogdens)
        assert callable(self.priorsampler)
        assert callable(self.targetlogdens)
        assert callable(self.priorgradlogdens)
        assert callable(self.targetgradlogdens)

        
    def logdensity(self, particles, temperature):
        """
        returns the log density for a given temperature
        """
        assert temperature<=1.
        assert temperature>=0.
        #import ipdb; ipdb.set_trace()
        return (self.targetlogdens(particles, self.parameters)*temperature)+self.priorlogdens(particles, self.parameters)*(1.-temperature)

    def precalc_logdensity(self, particles):
        """
        function to precalc the logdensity
        """
        target = self.targetlogdens(particles, self.parameters)
        prior = self.priorlogdens(particles, self.parameters)
        return {'target' : target, 'prior' : prior}
    
    def gradlogdensity(self, particles, temperature):
        """
        returns the grad log density for a given temperature
        """
        assert temperature<=1.
        assert temperature>=0.
        return (self.targetgradlogdens(particles, self.parameters)*temperature)+self.priorgradlogdens(particles, self.parameters)*(1.-temperature)

def function_summary_particles(particles):
    return particles+particles**2

def test_continue_sampling(summary_particles_list, quantile, correlation_previous):
    """
    test on whether continue sampling or not
    """
    part1 = function_summary_particles(summary_particles_list[-2])
    part2 = function_summary_particles(summary_particles_list[-1])
    dim = summary_particles_list[0].shape[1]
    correleations_array = np.array([np.corrcoef(part1[:,i], part2[:,i])[1,0] for i in range(dim)])
    #np.array([np.corrcoef(summary_particles_list[4][:,i], summary_particles_list[5][:,i])[1,0] for i in range(dim)])
    fraction_low_autocorr = (correleations_array*correlation_previous)<quantile
    #import ipdb; ipdb.set_trace()
    if fraction_low_autocorr.mean()>=0.9:
        test_decision = True
    else: 
        test_decision = False
    quantile = quantile
    results_test_dict = {'test_decision' : test_decision, 'test_statistic' : fraction_low_autocorr.mean(), 'quantile' : quantile}
    correlation_previous = correleations_array*correlation_previous
    return(results_test_dict, correlation_previous)

def test_continue_sampling_gradients(summary_particles_list, quantile, temp_curr, temperedist, N_particles, dim):

    gradients_current = temperedist.gradlogdensity(summary_particles_list[-1], temp_curr)
    gradients_current_sum = gradients_current.mean(axis=0).sum()
    estimator_covar_current = gradients_current.transpose().dot(gradients_current)/N_particles
    estimator_covar_current_sum = estimator_covar_current.sum()
    stat_test = N_particles*(gradients_current_sum**2)/estimator_covar_current_sum
    test_decision = chi2.cdf(stat_test, dim) < quantile#proposalkerneldict['quantile_test']
    results_test_dict = {'test_decision' : test_decision, 'test_statistic' : stat_test, 'quantile' : quantile}

    return(results_test_dict)


def logincrementalweights(particles, temperedist, temperature):
    """
    returns the log incremental weights
    """
    temperatureprevious, temperaturecurrent  = temperature[0], temperature[1]
    assert temperaturecurrent >= temperatureprevious
    numerator =  temperedist.logdensity(particles, temperature=temperaturecurrent)
    denominator = temperedist.logdensity(particles, temperature=temperatureprevious)
    return numerator - denominator

def reweight(particles, temperedist, temperature, weights_normalized):
    """
    log incremental weights based on the temperature
    """
    incweights = logincrementalweights(particles, temperedist, temperature)+np.log(weights_normalized)
    return incweights

def resample(particles, weights_normalized):
    """
    resampling the particles
    """
    ancestors = resampling.systematic_resample(weights_normalized)
    weights_normalized = np.ones(ancestors.shape[0])/ancestors.shape[0]
    return particles[ancestors, :], weights_normalized

def ESS(weights_normalized):
    return (1/(weights_normalized**2).sum())/weights_normalized.shape[0]


def ESS_target_dichotomic_search(temperaturenext, temperatureprevious, ESStarget, particles, temperedist, weights_normalized):
    """
    ESS target that is based to the dichotomic search algortihm
    """
    weights = reweight(particles, temperedist, [temperatureprevious, temperaturenext], weights_normalized)
    weights_normalized_new = np.exp(weights)/np.exp(weights).sum()
    ESS_res = ESS(weights_normalized_new)
    #import ipdb; ipdb.set_trace()
    return ESS_res-ESStarget

def ESS_target_dichotomic_search_simplified(temperaturenext, temperatureprevious, ESStarget, precalc_dict):
    """
    ESS target that is based to the dichotomic search algortihm, simplified version that is based on the precalculated 
    dictionary of the log density
    """
    precalc_logtarget = precalc_dict['target']
    precalc_logprior = precalc_dict['prior']
    weights = temperaturenext*precalc_logtarget+(1-temperaturenext)*precalc_logprior-temperatureprevious*precalc_logtarget-(1-temperatureprevious)*precalc_logprior
    #weights = reweight(particles, temperedist, [temperatureprevious, temperaturenext], weights_normalized)
    weights_normalized_new = np.exp(weights)/np.exp(weights).sum()
    ESS_res = ESS(weights_normalized_new)
    #import ipdb; ipdb.set_trace()
    return ESS_res-ESStarget


def logincrementalweights_is(particles, particles_previous, temperedist, temperature, perfkerneldict, selector_energy=-1):
    """
    returns the log incremental weights
    """
    temperatureprevious, temperaturecurrent  = temperature[0], temperature[1]
    assert temperaturecurrent >= temperatureprevious
    #import ipdb; ipdb.set_trace()
    denominator = -perfkerneldict['energy_kinetic'][:,0]+temperedist.logdensity(particles_previous, temperatureprevious)
    numerator = -perfkerneldict['energy_kinetic'][:,selector_energy]+temperedist.logdensity(particles, temperaturecurrent)
    # previous version for MCMC type kernel
    #numerator =  temperedist.logdensity(particles, temperature=temperaturecurrent)
    #denominator = temperedist.logdensity(particles, temperature=temperatureprevious)
    #import ipdb; ipdb.set_trace()
    return numerator - denominator

def reweight_is(particles, particles_previous, temperedist, temperature, weights_normalized, perfkerneldict, selector_energy=-1):
    """
    log incremental weights based on the temperature
    """
    #import ipdb; ipdb.set_trace()
    incweights = logincrementalweights_is(particles, particles_previous, temperedist, temperature, perfkerneldict, selector_energy)+np.log(weights_normalized)
    return incweights



def ESS_target_dichotomic_search_is(temperaturenext, temperatureprevious, ESStarget, particles, particles_previous, temperedist, weights_normalized, perfkerneldict):
    weights = reweight_is(particles, particles_previous, temperedist, [temperatureprevious, temperaturenext], weights_normalized, perfkerneldict)
    weights_normalized_new = np.exp(weights)/np.exp(weights).sum()
    ESS_res = ESS(weights_normalized_new)
    #import ipdb; ipdb.set_trace()
    return ESS_res-ESStarget


def sample_weighted_epsilon_L(perfkerneldict, proposalkerneldict, high_acceptance=False):
    """
    function that samples weighted epsilon and L 
    """
    # case of mala and rw
    if len(perfkerneldict['energy'].shape)==1:
        energy = perfkerneldict['energy'][:,np.newaxis]
        #squarejumpdist = perfkerneldict['squarejumpdist'][:,np.newaxis]
        squarejumpdist = perfkerneldict['squarejumpdist_mahalanobis'][:,np.newaxis]
        N_particles, L_total = energy.shape[0], 1
        energy_quant_reg = energy
    # case of hmc
    else: 
        energy = -perfkerneldict['energy'][:,1:]+perfkerneldict['energy'][:,:1]
        #squarejumpdist = perfkerneldict['squarejumpdist'][:,1:]
        squarejumpdist = perfkerneldict['squarejumpdist_mahalanobis'][:,1:]
        N_particles, L_total = energy.shape
        energy_quant_reg = energy[:,-1]

    # procedure that filters out trajectories with too high variation
    if 'trajectory_selector_energy' in proposalkerneldict.keys():
        if proposalkerneldict['trajectory_selector_energy']:
            #import ipdb; ipdb.set_trace()
            #from matplotlib import pyplot as plt
            #plt.plot(energy[:,:].transpose()); plt.show()
            selector_trajectory = ~np.any(np.abs(energy[:,:])>0.05, axis=1)
        else: 
            selector_trajectory = np.ones(N_particles, dtype=bool)
    else: 
        selector_trajectory = np.ones(N_particles, dtype=bool)
    
    energy = energy[selector_trajectory,:]
    epsilon = np.tile(perfkerneldict['epsilon'][selector_trajectory,:], (1, L_total))
    L_steps = np.tile(np.arange(1, L_total+1), (selector_trajectory.sum(), 1))
    squarejumpdist = squarejumpdist[selector_trajectory,:]

    energy_weights = np.clip(np.exp(energy), 0., 1.)
    # flatten arrays
    squarejumpdist_flat = squarejumpdist.flatten()
    L_steps_flat = L_steps.flatten()
    weights_flat = energy_weights.flatten()
    #import ipdb; ipdb.set_trace()
    weighted_squarejumpdist_flat = squarejumpdist_flat*weights_flat/(L_steps_flat)
    epsilon_flat = epsilon.flatten()
    
    # filter out the terms that degenerated
    if np.isnan(weighted_squarejumpdist_flat).any():
        nan_selector = np.isnan(weighted_squarejumpdist_flat)
        weighted_squarejumpdist_flat[nan_selector] = 0
    # choose based on sampling
    weights_esjd = weighted_squarejumpdist_flat/np.nansum(weighted_squarejumpdist_flat)
    if np.isnan(weights_esjd).any():
        nan_selector = np.isnan(weighted_squarejumpdist_flat)
        weighted_squarejumpdist_flat[nan_selector] = 0
        #import ipdb; ipdb.set_trace()
    #import ipdb; ipdb.set_trace()
    #weights_esjd = weighted_squarejumpdist_flat/weighted_squarejumpdist_flat.sum()
    res = np.random.choice(range(weights_esjd.shape[0]), size=N_particles, p=weights_esjd)
    L_next = L_steps_flat[res]
    #L_next = np.int(np.ceil(L_next.mean()))
    epsilon_next = epsilon_flat[res][:, np.newaxis]
    #import ipdb; ipdb.set_trace()
    if True: 
        import seaborn as sns
        sns.set_style("whitegrid")
        plt.rc('font', size=20)      
        fig = plt.figure()
        ax = plt.axes(projection='3d')
        #ax = fig.add_subplot(111, projection='3d')

        #surf = 
        ax.plot_trisurf(L_steps_flat, epsilon_flat, weighted_squarejumpdist_flat, cmap=cm.binary, linewidth=0.4)
        #fig.colorbar(surf)

        #ax.xaxis.set_major_locator(MaxNLocator(5))
        #ax.yaxis.set_major_locator(MaxNLocator(6))
        #ax.zaxis.set_major_locator(MaxNLocator(5))
        ax.set_xlabel('x')
        ax.set_ylabel('y')
        ax.set_zlabel('z')
        #fig.tight_layout()
        #import ipdb; ipdb.set_trace()
        for item in ([ax.title, ax.xaxis.label, ax.yaxis.label, ax.zaxis.label] + ax.get_xticklabels() + ax.get_yticklabels()+ax.get_zticklabels()):
            item.set_fontsize(14)
        #plt.axis('off')
        fig.savefig('3D_temp_%s.pdf' %(perfkerneldict['temp']))

        fig.clf()
        #ax.clf()
        #surf.clf()
        #plt.show()
        #import ipdb; ipdb.set_trace()
        plt.hist(epsilon_next)
        plt.savefig('hist_epsilon_temp_%s.png' %(perfkerneldict['temp']))
        plt.clf()
        plt.hist(L_next)
        plt.savefig('hist_L_temp_%s.png' %(perfkerneldict['temp']), bbox_inches='tight')
        plt.clf()

    # choose the argmax
    #index_max = np.argmax(weighted_squarejumpdist_flat)
    #epsilon_next = epsilon_flat[index_max]
    #L_next = L_steps_flat[index_max]

    return epsilon_next, L_next



def sample_weighted_epsilon_L_fearnhead_taylor(perfkerneldict, proposalkerneldict):
    """
    function that samples weighted epsilon and L 
    """
    
    # case of mala and rw
    if len(perfkerneldict['energy'].shape)==1:
        energy = perfkerneldict['energy'][:,np.newaxis]
        #squarejumpdist = perfkerneldict['squarejumpdist'][:,np.newaxis]
        squarejumpdist = perfkerneldict['squarejumpdist_mahalanobis'][:,np.newaxis]
        N_particles, L_total = energy.shape[0], 1
        energy_quant_reg = energy
        L_steps = np.ones(N_particles)
    # case of hmc
    else: 
        energy = -perfkerneldict['energy'][:,1:]+perfkerneldict['energy'][:,:1]
        #squarejumpdist = perfkerneldict['squarejumpdist'][:,-1]
        squarejumpdist = perfkerneldict['squarejumpdist_mahalanobis'][:,-1]
        N_particles, L_total = energy.shape
        energy_quant_reg = energy[:,-1]
        L_steps = perfkerneldict['L']
    
    selector_trajectory = np.ones(N_particles, dtype=bool)
    
    energy = energy[selector_trajectory,:]
    epsilon = perfkerneldict['epsilon'][selector_trajectory,:]
    #import ipdb; ipdb.set_trace()
    L_steps = L_steps[selector_trajectory]
    squarejumpdist = squarejumpdist[selector_trajectory]

    energy_weights = np.clip(np.exp(energy), 0., 1.)
    # flatten arrays
    squarejumpdist_flat = squarejumpdist.flatten()
    L_steps_flat = L_steps.flatten()
    weights_flat = energy_weights.flatten()
    weighted_squarejumpdist_flat = squarejumpdist_flat*weights_flat/(L_steps_flat)
    epsilon_flat = epsilon.flatten()
    
    # filter out the terms that degenerated
    if np.isnan(weighted_squarejumpdist_flat).any():
        nan_selector = np.isnan(weighted_squarejumpdist_flat)
        weighted_squarejumpdist_flat[nan_selector] = 0
    # choose based on sampling
    weights_esjd = weighted_squarejumpdist_flat/np.nansum(weighted_squarejumpdist_flat)
    if np.isnan(weights_esjd).any():
        nan_selector = np.isnan(weighted_squarejumpdist_flat)
        weighted_squarejumpdist_flat[nan_selector] = 0
        #import ipdb; ipdb.set_trace()
    #import ipdb; ipdb.set_trace()
    #weights_esjd = weighted_squarejumpdist_flat/weighted_squarejumpdist_flat.sum()
    res = np.random.choice(range(weights_esjd.shape[0]), size=N_particles, p=weights_esjd)
    L_next = L_steps_flat[res]
    #L_next = np.int(np.ceil(L_next.mean()))
    epsilon_next = epsilon_flat[res][:, np.newaxis]
    
    #import matplotlib.pyplot as plt
    #import seaborn as sns
    #sns.distplot(L_next); plt.show()
    #sns.distplot(L_next, hist_kws={'cumulative': True}, kde_kws={'cumulative': True}); plt.show()
    
    #import ipdb; ipdb.set_trace()
    return epsilon_next, L_next


def quantile_regression_epsilon(perfkerneldict, proposalkerneldict):
    """
    function that does the quantile regression 
    for getting epsilon max
    """
    target = abs(np.log(proposalkerneldict['target_probability']))
    # case of mala and rw
    if len(perfkerneldict['energy'].shape)==1:
        energy = perfkerneldict['energy']
        energy_quant_reg = energy
    # case of hmc
    else: 
        energy = -perfkerneldict['energy'][:,1:]+perfkerneldict['energy'][:,:1]
        energy_quant_reg = energy[:,-1]
    epsilon = perfkerneldict['epsilon'].flatten()
    #import ipdb; ipdb.set_trace()
    if np.isnan(energy_quant_reg).any() or np.isinf(energy_quant_reg).any():
        #import ipdb; ipdb.set_trace()
        selector = np.isfinite(energy_quant_reg)
        energy_quant_reg = energy_quant_reg[selector]
        epsilon = epsilon[selector]
        print('discard nan in energy')
    try:
        max_selector = abs(energy_quant_reg)<abs(np.log(proposalkerneldict['target_probability']))
        epsilon_max_simple = max(epsilon[max_selector])
    except:
        try: epsilon_max_simple =  max(epsilon[np.argmax(energy_quant_reg)])
        except: epsilon_max_simple =  max(epsilon)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            
            energy_quant_reg_clipped =  np.clip(abs(energy_quant_reg) , 0, 10**6)
            quant_reg = QuantReg(energy_quant_reg_clipped, epsilon**2)
            res_median = quant_reg.fit()
            res_lower = quant_reg.fit(0.5)
            #res_upper = quant_reg.fit(0.75)
            epsilon_max_quant = (target/res_lower.params)**0.5
            epsilon_next = (target/res_median.params)**0.5
    except:
        import ipdb; ipdb.set_trace()
        
    
    
    #import ipdb; ipdb.set_trace()
    
    #epsilon_min = (target/res_upper.params)**0.5
    epsilon_max = np.max([epsilon_max_quant, epsilon_max_simple])
    if np.isinf(epsilon_next):
        epsilon_next = np.mean(epsilon)
        #import ipdb; ipdb.set_trace()

    if False:
        #import ipdb; ipdb.set_trace()
        from matplotlib import pyplot as plt
        import seaborn as sns
        plt.rc('font', size=20)
        sns.set_style("whitegrid")

        plt.scatter(y=energy_quant_reg, x = epsilon, color='blue')
        plt.xlabel('epsilon', fontsize=14)
        plt.ylabel('Variation energy', fontsize=14)
        #plt.plot(epsilon, res_median.params*(epsilon**2).flatten(), color='red')
        #plt.plot(epsilon, res_lower.params*(epsilon**2).flatten(), color='grey')
        #plt.scatter(y=res_lower.params*(epsilon_current**2).flatten(), x = (epsilon_current).flatten(), color='grey')
        
        #plt.title('Variation in energy according to epsilon')
        plt.savefig('energy_temp_%s.pdf' %(perfkerneldict['temp']))
        #plt.tight_layout(pad=1.2)
        plt.clf()
    
    #import matplotlib.pyplot as plt
    #import seaborn as sns
    #import ipdb; ipdb.set_trace()
    #plt.scatter(y=energy_quant_reg, x=perfkerneldict['L'])
    return epsilon_next, epsilon_max



def tune_mcmc_parameters(perfkerneldict, proposalkerneldict, high_acceptance=False):
    """
    function that tunes the parameters
    input: dictionnary with the performance of the kernels
    output:
    """
    if proposalkerneldict['sample_eps_L']:
        epsilon_next, L_next = sample_weighted_epsilon_L(perfkerneldict, proposalkerneldict, high_acceptance=high_acceptance)
        __, epsilon_max = quantile_regression_epsilon(perfkerneldict, proposalkerneldict)
    else: 
        epsilon_next, epsilon_max = quantile_regression_epsilon(perfkerneldict, proposalkerneldict)
        L_next = proposalkerneldict['L_steps']

    res_dict = {'epsilon_next' : epsilon_next, 'L_next' : L_next, 'epsilon_max': epsilon_max, 'L_max':  L_next.max()}
    return res_dict

def tune_mcmc_parameters_fearnhead_taylor(perfkerneldict, proposalkerneldict, high_acceptance=False):
    """
    function that tunes the parameters
    input: dictionnary with the performance of the kernels
    output:
    """
    
    epsilon_next, L_next = sample_weighted_epsilon_L_fearnhead_taylor(perfkerneldict, proposalkerneldict)
    epsilon_max = 0.

    res_dict = {'epsilon_next' : epsilon_next, 'L_next' : L_next, 'epsilon_max': epsilon_max, 'L_max': L_next.max()}
    return res_dict


def tune_mcmc_parameters_simple(perfkerneldict, proposalkerneldict, high_acceptance=False):
    """
    function that tunes the parameters
    input: dictionnary with the performance of the kernels
    output:
    """
    
    epsilon_next, L_next = sample_weighted_epsilon_L_fearnhead_taylor(perfkerneldict, proposalkerneldict)
    __, epsilon_max = quantile_regression_epsilon(perfkerneldict, proposalkerneldict)

    # procedure for adapting 
    L_max_current = L_next.max()
    if (L_next==L_max_current).mean()>0.1:
        L_max = L_max_current+5
    elif (L_next==L_max_current).mean()<0.05:
        L_max = L_max_current-5
        if L_max<1:
            L_max = L_max_current
    else: 
        L_max = L_max_current

    res_dict = {'epsilon_next' : epsilon_next, 'L_next' : L_next, 'epsilon_max': epsilon_max, 'L_max' : L_max}
    return res_dict



def hilbert_sampling(particles, weights_normalized, u_randomness):
    # order the qmc points first
    u_to_order = u_randomness[:,0]
    u_indices_ordering = np.argsort(u_to_order)
    u_ordered = u_to_order[u_indices_ordering]
    # hilbert sort the particles
    particles_permutation  = brutehilbertsort(particles)
    # use the permutation on the weights
    weights_normalized_ordered = weights_normalized[particles_permutation]
    # samples ancestors
    ancestors = resampling_inverse_transform(u_ordered, weights_normalized_ordered)
    #particles_resampled = np.copy(particles[ancestors[particles_permutation.tolist()].tolist(), :])
    particles_resampled = np.copy(particles[particles_permutation[ancestors.tolist()].tolist(), :])
    u_randomness_ordered = u_randomness[u_indices_ordering, :]
    weights_normalized_new = np.ones(weights_normalized.shape)/weights_normalized.shape[0]
    return particles_resampled, weights_normalized_new, u_randomness_ordered


def resampling_is(particles, weights_normalized, u_randomness):
    ancestors = resampling.systematic_resample(weights_normalized)
    particles_resampled = particles[ancestors,:]
    weights_normalized_new = np.ones(weights_normalized.shape)/weights_normalized.shape[0]
    return particles_resampled, weights_normalized_new, u_randomness


if __name__ == '__main__':
    print(resampling.multinomial_resample([0.5, 0.5]))
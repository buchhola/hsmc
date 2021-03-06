# IS version of the SMC sampler
# smc sampler
from __future__ import print_function
from __future__ import division

import numpy as np
import sys
sys.path.append("/home/alex/python_programming/help_functions")
sys.path.append("/home/alex/Dropbox/smc_hmc/python_smchmc")

import numpy as np
from smc_sampler_functions.functions_smc_help import logincrementalweights_is, reweight_is, ESS_target_dichotomic_search_is, tune_mcmc_parameters, ESS, test_continue_sampling
from functools import partial

import sys
sys.path.append("../help")
from help import resampling
from help import dichotomic_search
import inspect
import time
import copy
import pickle
import datetime
import os

from help.f_rand_seq_gen import random_sequence_qmc, random_sequence_rqmc, random_sequence_mc
from help.gaussian_densities_etc import gaussian_vectorized
from smc_sampler_functions.functions_smc_help import hilbert_sampling, resampling_is




def smc_sampler_is_qmc(temperedist, parameters, proposalkerneldict, verbose=False):
    """
    sqmc sampler, takes as input 
    the temperedist (class instance)
    parameters (dict)
    proposalkerneldict_temp (dict)
    """
    N_particles = parameters['N_particles']
    dim = parameters['dim']
    T_time = parameters['T_time']
    proposalkerneldict_temp = copy.copy(proposalkerneldict)
    if not parameters['autotempering']:
        temperatures = np.linspace(0,1,T_time)
        temperatures = np.hstack((temperatures, 1.)).flatten()
    
    proposalkernel_tune = proposalkerneldict_temp['proposalkernel_tune']
    proposalkernel_sample = proposalkerneldict_temp['proposalkernel_sample']
    move_steps = proposalkerneldict['move_steps']
    unif_sampler = proposalkerneldict['unif_sampler']
    assert callable(proposalkernel_tune)
    assert callable(proposalkernel_sample)
    assert isinstance(proposalkerneldict_temp, dict)
    
    # prepare for the results
    Z_list = []; mean_list = []; var_list = []
    ESS_list = []; acceptance_rate_list = []
    temp_list = []; perf_list = []; test_dict_list = []

    print('Starting sqmc is sampler')
    time_start = time.time()
    
    if not parameters['autotempering']:
        temperatures = np.linspace(0,1,T_time)
        temperatures = np.hstack((temperatures, 1.)).flatten()
    
    # pre allocate data
    u_randomness = unif_sampler(dim*2, 0, N_particles)
    particles_initial = temperedist.priorsampler(parameters, u_randomness[:, :dim])
    #particles_initial = gaussian_vectorized(u_randomness[:, :dim])
    particles, perfkerneldict = proposalkernel_sample(particles_initial, u_randomness[:, dim:], proposalkerneldict_temp, temperedist, 0)
    #import ipdb; ipdb.set_trace()
    weights_normalized = np.ones(N_particles)/N_particles
    weights = reweight_is(particles, particles_initial, temperedist, [0, 0], weights_normalized, perfkerneldict)

    max_weights = np.max(weights)
    Z_hat = max_weights+np.log(np.exp(weights-max_weights).sum())
    weights_normalized = np.exp(weights -(max_weights +np.log(np.exp(weights-max_weights).sum())))

    # store results
    Z_list.append(np.copy(Z_hat))
    ESS_list.append(ESS(weights_normalized))
    acceptance_rate_list.append(perfkerneldict['acceptance_rate'])
    means_weighted = np.average(particles, weights=weights_normalized, axis=0)
    variances_weighted = np.cov(particles, rowvar=False, aweights=weights_normalized)
    mean_list.append(means_weighted)
    var_list.append(variances_weighted)
    temp_list.append(0)
    # delete some attributes from the perfkerneldict, 
    del perfkerneldict['energy']; del perfkerneldict['squarejumpdist']
    perf_list.append(perfkerneldict)


    #loop sampler
    temp_curr = 0.
    temp_next = 0.
    counter_while = 0
    print('Now runing smc sampler with %s kernel' %proposalkerneldict_temp['proposalname'])
    time_start = time.time()

    while temp_curr <= 1.:

        # generate randomness
        u_randomness = unif_sampler(dim+1, 0, N_particles)
        # hilbert sampling
        if 'qmc' in unif_sampler.__name__:
            particles_resampled, weights_normalized, u_randomness_ordered = hilbert_sampling(particles, weights_normalized, u_randomness)
        else: 
            particles_resampled, weights_normalized, u_randomness_ordered = resampling_is(particles, weights_normalized, u_randomness)


        # propagate
        if parameters['adaptive_covariance'] and temp_curr != 0.:
            proposalkerneldict_temp['covariance_matrix'] = np.diag(np.diag(var_list[-1]))
        
        # tune the kernel
        if proposalkerneldict_temp['tune_kernel']:
            if verbose: 
                print("now tuning")
            # tune the parameters 
            proposalkerneldict_temp['L_steps'] = np.copy(proposalkerneldict['L_steps'])
            proposalkerneldict_temp['epsilon_sampled'] = np.random.random((N_particles,1))*proposalkerneldict_temp['epsilon_max']
            particles, perfkerneldict = proposalkernel_tune(particles_resampled, u_randomness_ordered[:, 1:], proposalkerneldict_temp, temperedist, temp_curr)
            perfkerneldict['temp'] = temp_curr
            del proposalkerneldict_temp['epsilon_sampled'] # deleted because also available in output perfkerneldict
            
            results_tuning = tune_mcmc_parameters(perfkerneldict, proposalkerneldict_temp, high_acceptance=True)
            proposalkerneldict_temp['epsilon'] = results_tuning['epsilon_next']
            proposalkerneldict_temp['epsilon_max'] = results_tuning['epsilon_max']
            proposalkerneldict_temp['L_steps'] = results_tuning['L_next']
            #import ipdb; ipdb.set_trace()
        if verbose: 
            print("now sampling")

        particles, perfkerneldict = proposalkernel_sample(particles_resampled, u_randomness_ordered[:, 1:], proposalkerneldict_temp, temperedist, temp_curr)

        if False:
            
            L_max = perfkerneldict['L']
            temp_steps = 20
            temp_range = np.linspace(temp_curr, min(temp_curr+0.2,1.), temp_steps)
            array_results_ESS = np.zeros((L_max, temp_steps))
            for l in range(L_max):
                for t in range(temp_steps):
                    particles_inter = perfkerneldict['trajectory_particles'][0][:,:,l+1]
                    weights = reweight_is(particles_inter, particles_resampled, temperedist, [temp_curr, temp_range[t]], weights_normalized, perfkerneldict, selector_energy=l+1)
                    max_weights = np.max(weights)
                    weights_normalized_inter = np.exp(weights -(max_weights +np.log(np.exp(weights-max_weights).sum())))
                    array_results_ESS[l,t] = ESS(weights_normalized_inter)
            
            from matplotlib import pyplot as plt
            #plt.plot(array_results_ESS)
            #plt.show()
            
            from mpl_toolkits.mplot3d import Axes3D
            from matplotlib import cm
            from matplotlib.ticker import LinearLocator, FormatStrFormatter
            #ipdb.set_trace()
            X, Y = np.meshgrid(temp_range, range(L_max))
            fig = plt.figure()
            ax = fig.gca(projection='3d')
            surf = ax.plot_surface(X, Y, array_results_ESS, cmap=cm.coolwarm, linewidth=0, antialiased=False)
            plt.show()
            import ipdb; ipdb.set_trace()

        if not parameters['autotempering']:
            counter_while += 1
            temp_curr, temp_next = temperatures[counter_while-1], temperatures[counter_while]
        elif parameters['autotempering']:
            ESStarget = parameters['ESStarget']
            #partial_ess_target = partial(ESS_target_dichotomic_search, temperatureprevious=temp_curr, ESStarget=ESStarget, particles=particles_resampled, temperedist=temperedist, weights_normalized=weights_normalized)
            #temp_next = dichotomic_search.f_dichotomic_search(np.array([temp_curr,1.]), partial_ess_target, N_max_steps=100)
            #import ipdb; ipdb.set_trace()
            partial_ess_target = partial(ESS_target_dichotomic_search_is, 
                    temperatureprevious=temp_curr, 
                    ESStarget=ESStarget, particles=particles, 
                    particles_previous=particles_resampled, 
                    temperedist=temperedist, 
                    weights_normalized=weights_normalized, 
                    perfkerneldict=perfkerneldict)
            temp_next = dichotomic_search.f_dichotomic_search(np.array([temp_curr,1.]), partial_ess_target, N_max_steps=100)
            if partial_ess_target(temp_next)<-0.1:
                #import ipdb; ipdb.set_trace()
                temp_next = temp_curr
            print('temperature %s' %(temp_next), end='\r')
            assert temp_next <= 1.
            if temp_next > 1.:
                raise ValueError('temp greater than 1')
            if temp_curr == temp_next and temp_next < 1.:
                #import ipdb; ipdb.set_trace()
                print('not able to increase temperature')
        else:
            raise ValueError('tempering must be either auto or not')
        #import ipdb; ipdb.set_trace()
        

        weights = reweight_is(particles, particles_resampled, temperedist, [temp_curr, temp_next], weights_normalized, perfkerneldict)
        max_weights = np.max(weights)
        Z_hat = max_weights+np.log(np.exp(weights-max_weights).sum())
        weights_normalized = np.exp(weights -(max_weights +np.log(np.exp(weights-max_weights).sum())))

        # store results
        Z_list.append(np.copy(Z_hat))
        ESS_list.append(ESS(weights_normalized))
        acceptance_rate_list.append(perfkerneldict['acceptance_rate'])
        means_weighted = np.average(particles, weights=weights_normalized, axis=0)
        variances_weighted = np.cov(particles, rowvar=False, aweights=weights_normalized)
        mean_list.append(means_weighted)
        var_list.append(variances_weighted)
        temp_list.append(temp_next)
        # delete some attributes from the perfkerneldict, 
        del perfkerneldict['energy']; del perfkerneldict['squarejumpdist']
        perf_list.append(perfkerneldict)



        #import ipdb; ipdb.set_trace()
        print('sampling for temperature %s, current ESS %s' % (temp_curr, ESS(weights_normalized)), end='\r')
        for move in range(move_steps):
            u_randomness = unif_sampler(dim+1, 0, N_particles)
            # hilbert sampling or multinomial sampling
            if 'qmc' in unif_sampler.__name__:
                particles_resampled, weights_normalized, u_randomness_ordered = hilbert_sampling(particles, weights_normalized, u_randomness)
            else: 
                particles_resampled, weights_normalized, u_randomness_ordered = resampling_is(particles, weights_normalized, u_randomness)        # propagate


            # propagate
            #test_dict = test_continue_sampling(particles, temp_curr, temperedist, parameters['quantile_test'])
            #test_dict['temp'] = temp_curr
            #test_dict_list.append(test_dict)
            if False:#not test_dict['test_decision']:
                break
            else: 
                particles, perfkerneldict = proposalkernel_sample(particles_resampled, u_randomness_ordered[:, 1:], proposalkerneldict_temp, temperedist, temp_next)
                weights = reweight_is(particles, particles_resampled, temperedist, [temp_next, temp_next], weights_normalized, perfkerneldict)
                max_weights = np.max(weights)
                Z_hat = max_weights+np.log(np.exp(weights-max_weights).sum())
                weights_normalized = np.exp(weights -(max_weights +np.log(np.exp(weights-max_weights).sum())))

                # store results
                Z_list.append(np.copy(Z_hat))
                ESS_list.append(ESS(weights_normalized))
                acceptance_rate_list.append(perfkerneldict['acceptance_rate'])
                means_weighted = np.average(particles, weights=weights_normalized, axis=0)
                variances_weighted = np.cov(particles, rowvar=False, aweights=weights_normalized)
                mean_list.append(means_weighted)
                var_list.append(variances_weighted)
                temp_list.append(temp_next)
                # delete some attributes from the perfkerneldict, 
                del perfkerneldict['energy']; del perfkerneldict['squarejumpdist']
                perf_list.append(perfkerneldict)
            
            
            
        
        if temp_curr == 1.:
            break
        temp_curr = np.copy(temp_next)
            
            
    particles_resampled = particles
    time_end = time.time()
    run_time = time_end-time_start
    print('Sampler ended at time %s after %s seconds \n' %(len(temp_list), run_time))
    res_dict = {
        'mean_list' : mean_list,
        'var_list' : var_list,
        'particles_resampled' : particles_resampled, 
        'weights_normalized' : weights_normalized, 
        'Z_list' : Z_list, 
        'ESS_list' : ESS_list, 
        'acceptance_rate_list' : acceptance_rate_list,
        'temp_list' : temp_list,
        'parameters' : parameters,
        'proposal_kernel': proposalkerneldict_temp,
        'run_time' : run_time,
        'perf_list' : perf_list,
        'target_name' : temperedist.target_name,
        'L_mean' : np.array([iteration['L'] for iteration in perf_list]).mean(),
        'test_dict_list' : test_dict_list
        }
    #import ipdb; ipdb.set_trace()
    return res_dict


def repeat_sampling_is(samplers_list_dict, temperedist, parameters, M_num_repetions=50, save_res=True, save_res_intermediate=False, save_name=''):
    # function that repeats the sampling
    len_list = len(samplers_list_dict)
    dim = parameters['dim']
    N_particles = parameters['N_particles']
    norm_constant_list = np.zeros((len_list, M_num_repetions))
    mean_array = np.zeros((len_list, M_num_repetions, dim))
    var_array = np.zeros((len_list, M_num_repetions, dim, dim))
    ESJD_array = np.zeros((len_list, M_num_repetions))
    temp_steps_array = np.zeros((len_list, M_num_repetions))
    particles_array = np.zeros((N_particles, dim, len_list, M_num_repetions))
    names_samplers = [sampler['proposalname'] for sampler in samplers_list_dict]
    runtime_list = np.zeros((len_list, M_num_repetions))
    L_mean_array = np.zeros((len_list, M_num_repetions))
    root_folder = os.getcwd()
    if save_res:
        now = datetime.datetime.now().isoformat()
        os.mkdir('results_simulation_%s'%(now))
        os.chdir('results_simulation_%s'%(now))
    # run the samplers
    res_first_iteration = []
    for m_repetition in range(M_num_repetions):
        print("repetition %s of %s" %(m_repetition, M_num_repetions), end='\n')
        for k, sampler_dict in enumerate(samplers_list_dict):
            res_dict = smc_sampler_is_qmc(temperedist,  parameters, sampler_dict)
            # save the first instance
            if m_repetition == 0:
                res_first_iteration.append(res_dict)
            norm_constant_list[k, m_repetition] = np.sum(res_dict['Z_list'])
            mean_array[k, m_repetition,:] = res_dict['mean_list'][-1]
            ESJD_array[k, m_repetition] = res_dict['perf_list'][-1]['squarejumpdist_realized'].mean()
            L_mean_array[k, m_repetition] = res_dict['L_mean']
            temp_steps_array[k, m_repetition] = len(res_dict['temp_list'])
            #import ipdb; ipdb.set_trace()
            var_array[k, m_repetition,:,:] = res_dict['var_list'][-1]
            runtime_list[k, m_repetition] = res_dict['run_time']
            particles_array[:,:,k, m_repetition] = res_dict['particles_resampled']
            if save_res_intermediate:
                pickle.dump(res_dict, open('%sis_sampler_%s_rep_%s_dim_%s.p'%(save_name, names_samplers[k], m_repetition, parameters['dim']), 'wb'))
    all_dict = {'parameters': parameters, 
                'norm_const' : norm_constant_list, 
                'mean_array' : mean_array, 
                'var_array' :  var_array, 
                'names_samplers' : names_samplers,
                'M_num_repetions' : M_num_repetions,
                'target_name' : temperedist.target_name, 
                'particles_array' : particles_array, 
                'runtime_list' : runtime_list, 
                'ESJD_list': ESJD_array, 
                'temp_steps' : temp_steps_array, 
                'L_mean' : L_mean_array
                }
    if save_res:
        pickle.dump(all_dict, open('%s_%s_all_dict_is_sampler_dim_%s.p' %(temperedist.target_name, save_name, parameters['dim']), 'wb'))
    os.chdir(root_folder)
    #root_folder = os.getcwd()
    #import ipdb; ipdb.set_trace()
    return(all_dict, res_first_iteration)

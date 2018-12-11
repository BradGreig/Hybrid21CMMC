from py21cmmc import mcmc
from py21cmmc.mcmc import analyse
import pytest
import numpy as np
import os

from py21cmmc.mcmc.cosmoHammer import CosmoHammerSampler, HDFStorageUtil, Params

@pytest.fixture(scope="module")
def core():
    return mcmc.CoreCoevalModule(redshift=9, user_params={"HII_DIM": 35, "DIM": 70},
                                 cache_ionize=False, cache_init=False)

@pytest.fixture(scope="module")
def likelihood_coeval(tmpdirec):
    return mcmc.Likelihood1DPowerCoeval(simulate=True, datafile=os.path.join(tmpdirec.strpath, "likelihood_coeval"))


def test_core_coeval_not_setup():
    core = mcmc.CoreCoevalModule(redshift=9)

    with pytest.raises(mcmc.NotAChain):
        core.chain


def test_core_coeval_setup(core, likelihood_coeval):
    with pytest.raises(ValueError): # If simulate is not true, and no datafile given...
        lk = mcmc.Likelihood1DPowerCoeval()
        mcmc.build_computation_chain(core, lk)

    mcmc.build_computation_chain(core, likelihood_coeval)

    assert isinstance(core.chain, mcmc.cosmoHammer.LikelihoodComputationChain)
    assert core.initial_conditions_seed is not None

    ctx = core.chain.createChainContext()
    core.simulate_data(ctx)

    assert ctx.get("xHI") is not None
    assert ctx.get("brightness_temp") is not None

    assert not np.all(ctx.get("xHI")==0)
    assert not np.all(ctx.get("brightness_temp")==0)


def test_mcmc(core, likelihood_coeval, tmpdirec):
    chain = mcmc.run_mcmc(
        core, likelihood_coeval, model_name="TEST",continue_sampling=False, datadir=tmpdirec.strpath,
        params=dict(HII_EFF_FACTOR=[30.0, 10.0, 50.0, 3.0], ION_Tvir_MIN=[4.7, 2, 8, 0.1]),
        walkersRatio=2, burninIterations=0, sampleIterations=2, threadCount=1
    )

    samples_from_chain = analyse.get_samples(chain)
    samples_from_file = analyse.get_samples(os.path.join(tmpdirec.strpath, "TEST"))

    # make sure reading from file is the same as the chain.
    assert samples_from_chain.iteration == samples_from_file.iteration
    assert np.all(samples_from_file.accepted == samples_from_chain.accepted)
    assert np.all(samples_from_file.get_chain() == samples_from_chain.get_chain())

    assert all([c in ['HII_EFF_FACTOR', "ION_Tvir_MIN"] for c in samples_from_chain.param_names])
    assert samples_from_chain.has_blobs
    assert samples_from_chain.param_guess['HII_EFF_FACTOR'] == 30.0
    assert samples_from_chain.param_guess['ION_Tvir_MIN'] == 4.7


def test_continue_burnin(core, likelihood_coeval, tmpdirec):
    with pytest.raises(AssertionError): # needs to be sampled for at least 1 iteration!
        chain = mcmc.run_mcmc(
            core, likelihood_coeval, model_name="TESTBURNIN", continue_sampling=False, datadir=tmpdirec.strpath,
            params=dict(HII_EFF_FACTOR=[30.0, 10.0, 50.0, 3.0], ION_Tvir_MIN=[4.7, 2, 8, 0.1]),
            walkersRatio=2, burninIterations=1, sampleIterations=0, threadCount=1
        )

    chain = mcmc.run_mcmc(
        core, likelihood_coeval, model_name="TESTBURNIN", continue_sampling=False, datadir=tmpdirec.strpath,
        params=dict(HII_EFF_FACTOR=[30.0, 10.0, 50.0, 3.0], ION_Tvir_MIN=[4.7, 2, 8, 0.1]),
        walkersRatio=2, burninIterations=1, sampleIterations=1, threadCount=1
    )

    # HAVE TO SAVE THE CHAIN TO MEMORY HERE, BECAUSE THE OBJECT ACCESS THE FILE ON EVERY CALL,
    # WHICH MEANS IT CONSTANTLY UPDATES
    chain_b_chain = analyse.get_samples(chain, burnin=True).get_chain()
    chain_s_chain = analyse.get_samples(chain).get_chain()

    chain2 = mcmc.run_mcmc(
        core, likelihood_coeval, model_name="TESTBURNIN", continue_sampling=True, datadir=tmpdirec.strpath,
        params=dict(HII_EFF_FACTOR=[30.0, 10.0, 50.0, 3.0], ION_Tvir_MIN=[4.7, 2, 8, 0.1]),
        walkersRatio=2, burninIterations=2, sampleIterations=1, threadCount=1
    )

    burnin2 = analyse.get_samples(chain2, burnin=True)
    chain2_b_chain = burnin2.get_chain()
    chain2_s_chain = analyse.get_samples(chain).get_chain()

    assert burnin2.iteration == 2
    assert np.all(chain2_b_chain[:1] == chain_b_chain) # first 5 iteration should be unchanged

    # The actual samples *should* have been deleted, because they have different burnin times.
    assert not np.all(chain_s_chain == chain2_s_chain)

    chain3 = mcmc.run_mcmc(
        core, likelihood_coeval, model_name="TESTBURNIN", continue_sampling=True, datadir=tmpdirec.strpath,
        params=dict(HII_EFF_FACTOR=[30.0, 10.0, 50.0, 3.0], ION_Tvir_MIN=[4.7, 2, 8, 0.1]),
        walkersRatio=2, burninIterations=2, sampleIterations=2, threadCount=1
    )

    samples3 = chain3.samples
    assert samples3.iteration == 2

    chain3_b_chain = analyse.get_samples(chain3, burnin=True).get_chain()
    assert np.all(chain3_b_chain == chain2_b_chain)

    chain3_s_chain = analyse.get_samples(chain3).get_chain()
    assert np.all(chain2_s_chain == chain3_s_chain[:1])

    with pytest.raises(ValueError): #  don't run if we already have all samples, and let the user know!
        mcmc.run_mcmc(
            core, likelihood_coeval, model_name="TESTBURNIN", continue_sampling=True, datadir=tmpdirec.strpath,
            params=dict(HII_EFF_FACTOR=[30.0, 10.0, 50.0, 3.0], ION_Tvir_MIN=[4.7, 2, 8, 0.1]),
            walkersRatio=2, burninIterations=2, sampleIterations=2, threadCount=1
        )


def test_bad_continuation(core, likelihood_coeval, tmpdirec):
    "check if trying to continue a chain that isn't compatible with previous chain raises an error"

    mcmc.run_mcmc(
        core, likelihood_coeval, model_name="TESTBURNIN", continue_sampling=False,
        datadir=tmpdirec.strpath,
        params=dict(HII_EFF_FACTOR=[30.0, 10.0, 50.0, 3.0], ION_Tvir_MIN=[4.7, 2, 8, 0.1]),
        walkersRatio=2, burninIterations=0, sampleIterations=1, threadCount=1
    )

    with pytest.raises(RuntimeError):
        # core with different redshift
        core = mcmc.CoreCoevalModule(redshift=8, user_params={"HII_DIM": 35, "DIM": 70},
                                     cache_ionize=False, cache_init=False)
        mcmc.run_mcmc(
            core, likelihood_coeval, model_name="TESTBURNIN", continue_sampling=True, datadir=tmpdirec.strpath,
            params=dict(HII_EFF_FACTOR=[30.0, 10.0, 50.0, 3.0], ION_Tvir_MIN=[4.7, 2, 8, 0.1]),
            walkersRatio=2, burninIterations=0, sampleIterations=2, threadCount=1
        )


def test_init_pos_generator_good(core, likelihood_coeval, tmpdirec):

    params = Params(
        ("HII_EFF_FACTOR", [30.0, 10.0, 50.0, 10.0]),
        ("ION_Tvir_MIN", [4.7, 2, 8, 2])
    )

    chain = mcmc.build_computation_chain(core, likelihood_coeval, params=params)

    sampler = CosmoHammerSampler(
        continue_sampling=False,
        likelihoodComputationChain=chain,
        storageUtil=HDFStorageUtil(os.path.join(tmpdirec.strpath, "POSGENERATORTEST")),
        filePrefix=os.path.join(tmpdirec.strpath, "POSGENERATORTEST"),
        reuseBurnin=False,
        burninIterations=0,
        sampleIterations=1,
        walkersRatio=50
    )

    pos = sampler.createInitPos()

    assert all([chain.isValid(p) for p in pos])


def test_init_pos_generator_bad(core, likelihood_coeval, tmpdirec):

    params = Params(
        ("HII_EFF_FACTOR", [30.0, 29.0, 31.0, 100.0]),
        ("ION_Tvir_MIN", [4.7, 4.6, 4.8, 20])
    )

    chain = mcmc.build_computation_chain(core, likelihood_coeval, params=params)

    sampler = CosmoHammerSampler(
        continue_sampling=False,
        likelihoodComputationChain=chain,
        storageUtil=HDFStorageUtil(os.path.join(tmpdirec.strpath, "POSGENERATORTEST")),
        filePrefix=os.path.join(tmpdirec.strpath, "POSGENERATORTEST"),
        reuseBurnin=False,
        burninIterations=0,
        sampleIterations=1,
        walkersRatio=50
    )

    with pytest.raises(ValueError):
        pos = sampler.createInitPos()


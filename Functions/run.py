import cvxpy as cp
import numpy as np
import os
import math
import pandas as pd
from SOC_ACOPF import *
from Allocation_functions import *
from multiprocessing import Pool, Manager
import datetime as dt


def compute_SOC_ACOPF(sc, NT, baseMVA, N_bus, N_line, Yp, sending_node, receiving_node,
                      R_l, X_l, B_l, Pd, q_d, pn_bound, qn_bound, v_bound, G_n, B_n,
                      K_l, a, b, c, ESS_soc0, ESS_cha_bound, ESS_dis_bound, ESS_soc_bound, Pn_solar_bound, freq_scenario):
    # Function used to perform parallel progamming

    # Extract time-dependent indices
    idx_PV_sc = [np.where(Pn_solar_bound[sc, 1, :, time] > 0)[0].astype(int) for time in range(NT)]
    Yp_scenario = Yp * freq_scenario

    try:
        print(f"Starting scenario {sc}", flush=True)
        # Call the SOC_ACOPF_2D_alocation function
        cost, _, _, _, _, _, _, _, _, _, _, _, _, _, _, lambda_aloc, mu_aloc = SOC_ACOPF_2D_alocation(
            baseMVA, NT, N_bus, N_line, Yp_scenario[sc], sending_node, receiving_node, idx_PV_sc,
            R_l, X_l, B_l, Pd[sc], q_d,
            pn_bound[sc], qn_bound, v_bound,
            G_n, B_n, K_l,
            a, b, c,
            ESS_soc0, ESS_cha_bound, ESS_dis_bound, ESS_soc_bound)

        print(f"Finished scenario {sc}: Cost = {cost}", flush=True)
        # Return the results for storage
        return cost, lambda_aloc, mu_aloc

    except Exception as e:
        print(f"Error in compute_SOC_ACOPF for scenario {sc}: {e}", flush=True)
        raise

if __name__=="__main__":

    ################################################################ Parameters
    ESS_candidate = np.array([33, 85, 138, 116]) #Candidates nodes 
    group = 1 # set of scenario (from 1 to 6) # groups all contains 10 scenarios and only Pd and PV production is fluctuating
    num_processes = 4 # Number of processes to use (adjust based on your CPUs and memory)
    lim_iter = 100 # Max number of iteration of benders decompositions
    datapath = "Data/" # Change as a function of the loaded folder
    # It is possible to change other vales such as prices and costs detailed later

    ############################################################### Data import
    #Calculate time
    start_time = dt.datetime.now()
    sample_time = start_time

    # 632_0 data for Lausanne 
    bus_data = pd.read_csv(datapath+"632_0_bus_data.csv")
    bus_data = bus_data.sort_values(by="BUS_I").reset_index(drop=True) # maybe not usefull, to test later
    bus_index_to_bus_name = bus_data['BUS_I'].to_dict() # dictionary mapping the index number to bus ID
    bus_name_to_bus_index = {v: k for k, v in bus_index_to_bus_name.items()}
    bus_data = bus_data.reset_index().rename(columns = {"index":"grid_node"})

    branch_data = pd.read_csv(datapath+"632_0_branch_data.csv")
    generator_data = pd.read_csv(datapath+"632_0_generator_data.csv")

    stat_scenario = pd.read_csv(datapath+"Chaudron_scenarios.csv",delimiter=";")
    freq_scenario = stat_scenario.dp.to_numpy() / stat_scenario.dp.sum()

    # Processed data to get Pd and PV production per time step and per Scenario
    scenario_data = pd.read_csv(datapath+"groups/Clean_demand_632_group"+str(group)+".csv")

    # Used as data cleaning since I had one file with N nodes and the other with N-1 nodes
    # I then assumed that the slack was missing so I ajust values to fit 
    scenario_data.loc[scenario_data[scenario_data.grid_node>=(bus_data[bus_data.BUS_TYPE==3].grid_node).to_list()[0]].index,"grid_node"] += 1 

    NP = len(scenario_data.Period.unique()[:-2])
    N_bus = len(bus_data.grid_node.unique())
    N_line = len(branch_data)
    NT = 24
    baseMVA = generator_data.MBASE.max()

    ############################################################## Setting all costs
    #PV generation cost
    quad_cost_PV = 0
    lin_cost_PV = 26
    const_cost_PV = 0

    # Power cost
    index_slack = (bus_data[bus_data.BUS_TYPE==3].grid_node).to_list()[0]
    a_slack = np.zeros(N_bus)
    a_slack[index_slack] = 0
    a_slack = a_slack[:, np.newaxis] * np.ones((1, NT))
    b_slack = np.zeros(N_bus)
    b_slack[index_slack] = 200
    b_slack = b_slack[:, np.newaxis] * np.ones((1, NT))
    c_slack = np.zeros(N_bus)
    c_slack[index_slack] = 0
    c_slack = c_slack[:, np.newaxis] * np.ones((1, NT))

    ############################################################## Data preprocessing
    # creating the dataset for values that depends on time and scenario
    Pd = np.zeros((NP, N_bus, NT))
    Pn_solar_bound = np.zeros((NP, 2, N_bus, NT))
    a_PV = np.zeros((N_bus, NT))
    b_PV = np.zeros((N_bus, NT))
    c_PV = np.zeros((N_bus, NT))

    for sc in scenario_data.Period.unique()[:-2]-1:
        mask1 = (scenario_data.Period==sc+1)
        for time in scenario_data[mask1].Time.unique()-1:
            mask2 = (scenario_data.Time==time)
            intermediate_df = pd.merge(scenario_data[mask1 & mask2][["grid_node","Domestic_electricity","PV_production"]],
                bus_data[["grid_node"]],
                on="grid_node",
                how="right").fillna(0)
            Pd[sc,:,time] = intermediate_df.Domestic_electricity.to_numpy() /1000 /baseMVA # kWh to MW to p.u. 
            Pn_solar_bound[sc,1,:,time] = intermediate_df.PV_production.to_numpy() /1000 /baseMVA # kWh to MW to p.u.
            a_PV[:,time] = quad_cost_PV * np.ones(N_bus) # useless in that case since a,b,c constant
            b_PV[:,time] = lin_cost_PV * np.ones(N_bus) # useless in that case since a,b,c constant
            c_PV[:,time] = const_cost_PV * np.ones(N_bus) # useless in that case since a,b,c constant"""

    # expanding dataset for all other data that is not time or scenario dependant
    v_base_change = 20**2/11**2 # base voltage change from 20kV to 11kV

    # related to bus data
    q_d = bus_data.Qd.to_numpy() /baseMVA /5 #reactive power demand
    q_d= q_d[:, np.newaxis] * np.ones((1, NT))
    G_n = bus_data.Gs.to_numpy() / v_base_change
    G_n = G_n[:, np.newaxis] * np.ones((1, NT))
    B_n = bus_data.Bs.to_numpy() / v_base_change
    B_n = B_n[:, np.newaxis] * np.ones((1, NT))
    v_bound = bus_data[["Vmin","Vmax"]].to_numpy()
    v_bound = v_bound.T[:, :, np.newaxis] * np.ones((1, N_bus, NT))

    # related to generator data
    pn_bound = np.zeros((N_bus,2))
    qn_bound = np.zeros((N_bus,2))
    index_gen = generator_data["GEN_BUS"].map(bus_name_to_bus_index).to_numpy()
    generator_data["bus_index"] = index_gen
    for _, row in generator_data.iterrows():
        index = row["bus_index"]
        pn_bound[index,0] = -row["PMAX"] /baseMVA 
        pn_bound[index,1] = row["PMAX"] /baseMVA 
        qn_bound[index,0] = row["QMIN"] /baseMVA 
        qn_bound[index,1] = row["QMAX"] /baseMVA 
    pn_bound = pn_bound.T[np.newaxis,:, :, np.newaxis] * np.ones((NP, 1, N_bus, NT))
    pn_bound += Pn_solar_bound #Add the PV generation to other generation
    qn_bound = qn_bound.T[:, :, np.newaxis] * np.ones((1, N_bus, NT))

    # related to branch data
    sending_node = branch_data["F_BUS"].map(bus_name_to_bus_index).to_numpy().astype(int)
    receiving_node = branch_data["T_BUS"].map(bus_name_to_bus_index).to_numpy().astype(int)
    R_l = branch_data["BR_R"].to_numpy()*v_base_change
    R_l = R_l[:, np.newaxis] * np.ones((1, NT))
    X_l = branch_data["BR_X"].to_numpy()*v_base_change
    X_l = X_l[:, np.newaxis] * np.ones((1, NT))
    B_l = branch_data["BR_B"].to_numpy()/v_base_change
    B_l = B_l[:, np.newaxis] * np.ones((1, NT))
    K_l = 1 * np.ones(len(branch_data))  # Ampacity for each line
    K_l = K_l[:, np.newaxis] * np.ones((1, NT))

    # ESS candidate to index
    ESS_candidate = np.vectorize(bus_name_to_bus_index.get)(ESS_candidate).astype(int)

    # summing all cost
    a = a_slack+a_PV
    b = b_slack+b_PV
    c = c_slack+c_PV

    ###################################################################### Allocations constaints
    R_min = 0.05 / baseMVA * np.ones(N_bus)
    R_max = 4 / baseMVA * np.ones(N_bus)
    R_bounds = np.array([R_min,R_max])
    C_min = 0.1 / baseMVA * np.ones(N_bus)
    C_max = 7 /baseMVA * np.ones(N_bus)
    C_bounds = np.array([C_min,C_max])
    Fixed_cost = 100e3 #CHF/unit suppose to be e3
    Power_rating_cost = 2000e3 #CHF/p.u. 
    Energy_capacity_cost = 3000e3 #CHF/p.u. 


    obj_2nd = np.zeros(lim_iter) # objective function result from the 2nd step (SOC-ACOPF) 
    lambda_2nd = np.zeros((N_bus,NT,lim_iter)) # dual variable lambda result from the 2nd step (SOC-ACOPF) 
    mu_2nd = np.zeros((N_bus,NT,lim_iter)) # dual variable mu result from the 2nd step (SOC-ACOPF) 
    previous_rating = np.zeros((N_bus,lim_iter)) # saved rating value from iter = iter-1
    previous_cap = np.zeros((N_bus,lim_iter)) # saved capacity value from iter = iter-1
    ESS_loc = np.zeros((N_bus,lim_iter))
    alpha_store = np.zeros((lim_iter))
    upperB_save = np.zeros(lim_iter)
    lowerB_save = np.zeros(lim_iter)
    fairness_price = np.zeros(lim_iter)
    invest_save = np.zeros(lim_iter)


    ################################################################# MILP
    NP=10
    Yp=10
    obj_2nd = np.zeros((NP,lim_iter)) # objective function result from the 2nd step (SOC-ACOPF) 
    lambda_2nd = np.zeros((NP,N_bus,NT,lim_iter)) # dual variable lambda result from the 2nd step (SOC-ACOPF) 
    mu_2nd = np.zeros((NP,N_bus,NT,lim_iter)) # dual variable mu result from the 2nd step (SOC-ACOPF) 
    previous_rating = np.zeros((N_bus,lim_iter)) # saved rating value from iter = iter-1
    previous_cap = np.zeros((N_bus,lim_iter)) # saved capacity value from iter = iter-1
    ESS_loc = np.zeros((N_bus,lim_iter))
    alpha_store = np.zeros(lim_iter)
    upperB_save = np.zeros(lim_iter)
    lowerB_save = np.zeros(lim_iter)
    fairness_price = np.zeros(lim_iter)
    invest_save = np.zeros(lim_iter)
    Elapsed_time=np.zeros(lim_iter)

    iter = 0
    convergence = 0

    while ((iter < lim_iter) & (convergence==0)):

        obj_MP, invest_save[iter], ESS_loc[:,iter], Max_rating, Max_capacity, alpha_store[iter] = Allocation_2D(iter, NP, N_bus, ESS_candidate, R_bounds, C_bounds,
                                                                                        obj_2nd, lambda_2nd, mu_2nd, previous_rating, previous_cap,
                                                                                        Fixed_cost, Power_rating_cost,Energy_capacity_cost)

        ################################################################## Battery Alocation 
        IndESS = np.where(ESS_loc[:,iter]==1)[0]

        # Charging limits
        ESS_cha_l = np.zeros((N_bus, NT))  # Lower charging limits
        ESS_cha_u = np.zeros((N_bus, NT))  # Upper charging limits
        ESS_cha_u[IndESS, :] = Max_rating[IndESS].reshape(-1, 1)  # Max charging limits
        # Discharging limits
        ESS_dis_l = np.zeros((N_bus, NT))  # Lower discharging limits
        ESS_dis_u = np.zeros((N_bus, NT))  # Upper discharging limits
        ESS_dis_u[IndESS, :] = Max_rating[IndESS].reshape(-1, 1)  # Max discharging limits

        # State of Charge (SoC)
        ESS_soc0 = np.zeros((N_bus))
        ESS_soc_l = np.zeros((N_bus, NT))  # Lower SoC limits
        ESS_soc_u = np.zeros((N_bus, NT))  # Upper SoC limits
        ESS_soc_u[IndESS, :] = Max_capacity[IndESS].reshape(-1, 1)   # Max SoC limits

        ESS_cha_bound = np.array([ESS_cha_l,ESS_cha_u])
        ESS_dis_bound = np.array([ESS_dis_l,ESS_dis_u])
        ESS_soc_bound = np.array([ESS_soc_l,ESS_soc_u])

        ###################################################################### 2nd stage SOC-ACOPF
        # Prepare arguments for each `sc`
        inputs = [
            (sc, NT, baseMVA, N_bus, N_line, Yp, sending_node, receiving_node,
            R_l, X_l, B_l, Pd, q_d, pn_bound, qn_bound, v_bound, G_n, B_n,
            K_l, a, b, c, ESS_soc0, ESS_cha_bound, ESS_dis_bound, ESS_soc_bound, Pn_solar_bound, freq_scenario)
            for sc in range(NP)  # Loop over all scenarios `sc`
        ]

        # Create a pool of workers
        with Pool(processes=num_processes) as pool:
            results = pool.starmap(compute_SOC_ACOPF, inputs)

        # Unpack and store results
        for sc, (cost, lambda_aloc, mu_aloc) in enumerate(results):
            obj_2nd[sc, iter] = cost
            lambda_2nd[sc, :, :, iter] = -lambda_aloc
            mu_2nd[sc, :, :, iter] = -mu_aloc

        previous_rating[:,iter] = Max_rating
        previous_cap[:,iter] = Max_capacity

        ################################################################### Checking Convergence 
        upperB_save[iter] = np.sum(obj_2nd[:,iter]) + invest_save[iter] + fairness_price[iter]
        lowerB_save[iter] = obj_MP
        if (abs(upperB_save[iter]-lowerB_save[iter]) <= upperB_save[iter]*1e-2): convergence = 1
        print(f"Iteration {iter}, Gap: {abs(upperB_save[iter]-lowerB_save[iter])/upperB_save[iter]:.4f}")
        print("Upper bound :",upperB_save[iter])
        print("Lower bound :",lowerB_save[iter])
        
        #### Time calculation ####
        Elapsed_time[iter] = (dt.datetime.now() - sample_time).total_seconds()/60
        print(f"Elapsed time: {Elapsed_time[iter]}")
        sample_time = dt.datetime.now()

        # Continuing iteration
        iter+=1


    # Saving all files to analyze in another code
    res_path = 'res/nodes_group'+str(group)+'_'+str(ESS_candidate.tolist()) 
    os.makedirs(res_path, exist_ok=True)
    np.save(res_path+'/obj_2nd.npy', obj_2nd[:,:iter])
    np.save(res_path+'/lambda_2nd.npy', lambda_2nd[:,:,:,:iter])
    np.save(res_path+'/mu_2nd.npy', mu_2nd[:,:,:,:iter])
    np.save(res_path+'/previous_rating.npy', previous_rating[:,:iter])
    np.save(res_path+'/previous_cap.npy', previous_cap[:,:iter])
    np.save(res_path+'/ESS_loc.npy', ESS_loc[:,:iter])
    np.save(res_path+'/alpha_store.npy', alpha_store[:iter])
    np.save(res_path+'/upperB_save.npy', upperB_save[:iter])
    np.save(res_path+'/lowerB_save.npy', lowerB_save[:iter])
    np.save(res_path+'/invest_save.npy', invest_save[:iter])
    np.save(res_path+'/Elapsed_time.npy', Elapsed_time[:iter])
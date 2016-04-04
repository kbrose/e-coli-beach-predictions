import numpy as np
import read_data as rd

def R(E):
    return -11.74 + 9.397 * np.log10(E + 0.1)

def B(S, Vrecreation, R, Vhealth, C):
    return S * (Vrecreation - (R * Vhealth / 1000.0)) - C

def utility(TP, FN, FP, TN, B_TP, B_FN, B_FP, B_TN):
    return TP * B_TP + FN * B_FN + FP * B_FP + TN * B_TN

threshes = [235.0]

Vrecreations = [18.00, 39.00]

Vhealths = [500.0, 2000.0]

TPRs = [0.0]
FPRs = [0.0]

Cs = [0.0]

costs = []

ecoli = rd.read_data(read_water_sensor=False, read_weather_station=False)['Escherichia.coli']
ecoli = ecoli.dropna()

for thresh in threshes:
    for Vrecreation in Vrecreations:
        for Vhealth in Vhealths:
            for TPR in TPRs:
                for FPR in FPRs:
                    for C in Cs:
                        lo = (ecoli < thresh).sum()
                        hi = (ecoli >= thresh).sum()

                        TP = TPR * hi
                        FN = (1.0 - TPR) * hi
                        FP = FPR * lo
                        TN = (1.0 - FPR) * lo

                        lo_readings = ecoli[ecoli < thresh]
                        hi_readings = ecoli[ecoli > thresh]

                        B_TP = [B(-1, Vrecreation, R(E), Vhealth, C) for E in hi_readings]
                        if len(B_TP):
                            B_TP = sum(B_TP) / len(B_TP)
                        else:
                            B_TP = 0.0

                        B_FN = [B(1, Vrecreation, R(E), Vhealth, C) for E in hi_readings]
                        if len(B_FN):
                            B_FN = sum(B_FN) / len(B_FN)
                        else:
                            B_FN = 0.0

                        B_FP = [B(-1, Vrecreation, R(E), Vhealth, C) for E in lo_readings]
                        if len(B_FP):
                            B_FP = sum(B_FP) / len(B_FP)
                        else:
                            B_FP = 0.0

                        B_TN = [B(1, Vrecreation, R(E), Vhealth, C) for E in lo_readings]
                        if len(B_TN):
                            B_TN = sum(B_TN) / len(B_TN)
                        else:
                            B_TN = 0.0

                        costs.append(utility(TP, FN, FP, TN, B_TP, B_FN, B_FP, B_TN))

for c in costs:
    print(c)

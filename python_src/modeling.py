import numpy as np
import read_data as rd
import visualizations as viz
import matplotlib.pyplot as plt
import argparse
import pandas as pd
import datetime as dt
import os

# sklearn imports, may need to add more to use different models
import sklearn
import sklearn.ensemble
import sklearn.linear_model
import sklearn.decomposition

# Used for filtering
import scipy.stats


def model(timestamps, predictors, classes,
          classifier=None,
          prediction_attribute='predict_proba',
          hyperparams=None,
          roc_bounds=None,
          verbose=False):
    '''
    Creates several models using leave-one-year-out cross validation.

    ROC and PR curves are plotted as a side-effect.

    Parameters
    ----------
    timestamps : Nx1 pandas series of timestamps.
                 Each element should have a "year" attribute.
    predictors : NxM pandas DataFrame, all values should be numeric,
                 and there should be no NaN values.
    classes    : Nx1 array like of binary outcomes, e.g. True or False.
    classifier : sklearn classifier, should have the attributes "fit"
                 and "predict_proba" at the least.
    hyperparams: Dictionary of hyper parameters to pass to the
                 classifier method.
    prediction_attribute:
                 Name of the attribute of the classifier that returns
                 the probability of belonging to the positive class.
    roc_bounds : [min, max] values to use when computing partial AUC.
    verbose    : True if the clf.feature_importances_ should be printed

    Returns
    -------
    clfs   : Dictionary of (year, classifier) pairs, where the classifier
             is the model found by leaving the specified year out of the
             training set.
    roc_ax : the matplotlib axes object containing all of the ROC curves.
    pr_ax  : the matplotlib axes object containing all of the PR curves.
    '''
    if classifier is None:
        classifier = sklearn.ensemble.RandomForestClassifier
    if hyperparams is None:
        hyperparams = {}

    years = timestamps.map(lambda x: x.year)

    start = years.min()
    stop = years.max()

    stop = min(stop, 2014) # do not include 2015

    roc_fig, roc_ax = plt.subplots(1, figsize=[12, 9])
    pr_fig, pr_ax = plt.subplots(1, figsize=[12, 9])

    roc_fig.subplots_adjust(left=0.07, right=0.67)
    pr_fig.subplots_adjust(left=0.07, right=0.67)

    clfs = dict()
    auc_rocs = []

    for yr in range(start, stop+1):
        is_yr = years == yr
        yrs_diff = np.abs(years - yr)
        train_indices = np.array(~is_yr & (yrs_diff <= 3))
        test_indices = np.array(is_yr)

        clf = classifier(**hyperparams)
        clf.fit(predictors.ix[train_indices,:], classes[train_indices])

        clfs[yr] = clf

        predictions = getattr(clf, prediction_attribute)(predictors.ix[test_indices,:])[:,1]

        auc_roc = viz.roc(predictions,
                          classes[test_indices],
                          block_show=False,
                          ax=roc_ax,
                          bounds=roc_bounds)[3]
        auc_pr = viz.precision_recall(predictions,
                                      classes[test_indices],
                                      block_show=False,
                                      ax=pr_ax)[3]

        auc_roc = float(auc_roc)
        auc_rocs.append(auc_roc)
        auc_pr = float(auc_pr)

        roc_ax.get_lines()[-2].set_label(str(yr) + ' - AUC: {0:.5f}'.format(auc_roc))
        pr_ax.get_lines()[-2].set_label(str(yr) + ' - AUC: {0:.5f}'.format(auc_pr))

        if verbose:
            print('Year ' + str(yr))
            print('Feature importances:')
            feat_imps = clf.feature_importances_
            idxs = np.argsort(feat_imps)[::-1]
            max_width = max([len(c) for c in predictors.columns])

            for c, fi in zip(predictors.columns[idxs], feat_imps[idxs]):
                print('  {0:<{1}} : {2:.5f}'.format(c, max_width+1, fi))

    return clfs, auc_rocs, roc_ax, pr_ax


def prepare_data(df=None):
    '''
    Preps the data to be used in the model. Right now, the code itself must
    be modified to tweak which columns are included in what way.

    Parameters
    ----------
    df : Dataframe to use. If not specified, the dataframe is loaded automatically.

    Returns
    -------
    predictors : NxM DataFrame of the predictors for the classification problem.
    meta_info  : Nx3 DataFrame containing the columns 'Escherichia.coli' and
                 'Full_date', to be used, e.g., for leave-one-year-out cross
                 validation and creating the true class labels (elevated vs.
                 not elevated E. coli levels). The column 'Client.ID' is also
                 returned here, but is currently only used internally in this function.
    '''
    if df is None:
        df = rd.read_data()

    # Leaving 2015 as the final validation set
    df = df[df['Full_date'] < '1-1-2015']


    ######################################################
    #### Add derived columns here
    ######################################################

    df['DayOfYear'] = df['Full_date'].map(lambda x: x.dayofyear)
    derived_columns = ['DayOfYear']


    ######################################################
    #### List all columns you will use
    ######################################################

    # Meta columns are not used as predictors
    meta_columns = ['Client.ID', 'Full_date', 'Escherichia.coli']

    # Deterministic columns are known ahead of time, their actual values can be used.
    deterministic_columns = [
        # 'Client.ID',  # subsumed by the geographic flags

        # 'Sample.Collection.Time',

        'precipIntensity',
        'precipIntensityMax',
        'temperatureMin',
        'temperatureMax',
        'humidity',
        'windSpeed',
        'cloudCover',

        # 'sunriseTime',  # commenting for now since it is in absolute UNIX time

        'Days.Since.Last.Holiday',

        'flag_geographically_a_north_beach',
        'categorical_beach_grouping'
    ]

    # Deterministic columns are known ahead of time, their actual values are used.
    # These hourly variables have an additional parameter which defines what hours
    # should be used. For example, an entry
    #   'temperature':[-16,-13,-12,-11,-9,-3,0]
    # would indicate that the hourly temperature at offsets of
    # [-16,-13,-12,-11,-9,-3,0] from MIDNIGHT the day of should be included as
    # variables in the model.
    deterministic_hourly_columns = {
        'temperature': list(range(-19,-5)) + list(range(0,5)),
        'windSpeed':[1,2,3,4],
        'windBearing':[4],
        'pressure':[0],
        'cloudCover':[4],
        'humidity':[4],
        'precipIntensity':[-19, -15, -12, -8, -4, 0, 4]
    }
    for var in deterministic_hourly_columns:
        for hr in deterministic_hourly_columns[var]:
            deterministic_columns.append(var + '_hour_' + str(hr))

    # You can use these to remove columns where the trailing average is useful,
    # but the individual values are not.
    deterministic_hourly_columns_to_remove = {
        'precipIntensity':[-19, -15, -12, -8, -4, 0, 4],
    }

    # Historical columns have their previous days' values added to the predictors,
    # but not the current day's value(s) unless the historical column also exists
    # in the deterministic columns list.
    # Similar to the hourly columns, you need to specify which previous days
    # to include as variables. For example, below we have an entry
    #   'temperatureMax': range(1,4)
    # which indicates that the max temperature from 1, 2, and 3 days previous
    # should be included.
    historical_columns = {
        'temperatureMin': range(1,3),
        'temperatureMax': range(1,4),
        'humidity': range(1,3),
        'windSpeed': range(1,8),
        'cloudCover': range(1,8),
        'precipIntensity': [1],
        'Escherichia.coli': range(1,8)
    }
    historical_columns_list = list(historical_columns.keys())

    historical_columns_to_remove = {
        'windSpeed': range(1,8),
    }

    # Specific geo group average columns will have their means calculated
    # for each of the 6 geographic groups, and these values will be used as
    # predictors everywhere.
    specific_geo_group_average_columns = [
        '1_day_prior_Escherichia.coli',
        # 'trailing_average_daily_Escherichia.coli',
        # '1_day_prior_precipIntensity'
    ]

    # Binary geo group average columns will have their means calculated
    # for the beaches North and South of Navy Pier separately, and these
    # values will be used as predictors everywhere.
    binary_geo_group_average_columns = [
        '1_day_prior_Escherichia.coli',
        # 'trailing_average_daily_Escherichia.coli',
        # '1_day_prior_precipIntensity'
    ]


    ######################################################
    #### Get relevant columns, add historical data
    ######################################################

    all_columns = meta_columns + deterministic_columns + historical_columns_list + derived_columns
    all_columns = list(set(all_columns))

    df = df[all_columns]

    for var in historical_columns:
        df = rd.add_column_prior_data(
            df, var, historical_columns[var],
            beach_col_name='Client.ID', timestamp_col_name='Full_date'
        )

    df.drop((set(historical_columns_list) - set(deterministic_columns)) - set(meta_columns),
            axis=1, inplace=True)


    ######################################################
    #### Average the historical columns, fill in NaNs
    ######################################################

    # Creates a "trailing_average_daily_" column for each historical variable
    # which is simply the mean of the previous day columns of that variable.
    # NaN values for any previous day data is filled in by that mean value.
    for var in historical_columns:
        cname = 'trailing_average_daily_' + var
        rnge = historical_columns[var]
        if len(rnge) == 1:  # no need to create a trailing average of a single number...
            continue
        df[cname] = df[[str(n) + '_day_prior_' + var for n in rnge]].mean(1)
        for n in rnge:
            col = str(n) + '_day_prior_' + var
            if var in historical_columns_to_remove and n in historical_columns_to_remove[var]:
                df.drop(col, axis=1, inplace=True)
                continue
            if df[col].isnull().any():
                # df['isnull_trailing_mean_filled_' + col] = df[col].isnull()
                df[col].fillna(df[cname], inplace=True)

    # Do a similar process for the hourly data.
    for var in deterministic_hourly_columns:
        cname = 'trailing_average_hourly_' + var
        rnge = deterministic_hourly_columns[var]
        if len(rnge) == 1:  # no need to create a trailing average of a single number...
            continue
        df[cname] = df[[var + '_hour_' + str(n) for n in rnge]].mean(1)
        for n in rnge:
            col = var + '_hour_' + str(n)
            if var in deterministic_hourly_columns_to_remove and n in deterministic_hourly_columns_to_remove[var]:
                df.drop(col, axis=1, inplace=True)
                continue
            if df[col].isnull().any():
                # df['isnull_trailing_mean_filled_' + col] = df[col].isnull()
                df[col].fillna(df[cname], inplace=True)


    ######################################################
    #### Sample Collection Times
    ######################################################
    def clean_times(s):
        '''
        Takes in a string from the sample collection column and
        makes it machine readable if possible, and a NaN otherwise
        '''
        if type(s) is not str:
            if type(s) is dt.datetime or type(s) is dt.time:
                return dt.datetime(2016, 1, 1, hour=s.hour, minute=s.minute)

        try:
            if ':' not in s:
                return float('nan')
            i = s.index(':')
            hr = int(s[max(i - 2, 0):i])
            mn = int(s[i+1:i+3])

            return float(hr) + float(mn) / 60.0
        except:
            return float('nan')

    if 'Sample.Collection.Time' in df.columns:
        df['Sample.Collection.Time'] = df['Sample.Collection.Time'].map(lambda x: clean_times(x))


    ######################################################
    #### Group Average Variables
    ######################################################

    for var in specific_geo_group_average_columns:
        df2 = df[['Full_date', 'categorical_beach_grouping', var]]
        grp_df = df2.groupby(['Full_date', 'categorical_beach_grouping']).mean().unstack()

        # flatten the hierarchical column index
        grp_df.columns = ['_'.join(col) for col in grp_df.columns.values]

        df = df.merge(grp_df, how='left', left_on='Full_date', right_index=True)

    for var in binary_geo_group_average_columns:
        df2 = df[['Full_date', 'flag_geographically_a_north_beach', var]]
        grp_df = df2.groupby(['Full_date', 'flag_geographically_a_north_beach']).mean().unstack()

        # flatten the hierarchical column index
        grp_df.columns = ['_'.join([str(x) for x in col]) for col in grp_df.columns.values]

        df = df.merge(grp_df, how='left', left_on='Full_date', right_index=True)
    
    
    ######################################################
    #### PCA + Filters
    ######################################################

    forecast = pd.read_csv('../data/ExternalData/forecastio_hourly_weather.csv')
    cpd_data_path = '../data/ChicagoParkDistrict/raw/Standard 18 hr Testing/'
    cleanbeachnamesdf = pd.read_csv(cpd_data_path + 'cleanbeachnames.csv')
    beach_names_new_to_short = dict(zip(cleanbeachnamesdf['New'],
                                                cleanbeachnamesdf['Short_Names']))
    forecast['beach'] = forecast['beach'].map(lambda x: beach_names_new_to_short[x])
    forecast['windX'] = np.cos(forecast['windBearing'] * 180 / np.pi) * forecast['windSpeed']
    forecast['windY'] = np.sin(forecast['windBearing'] * 180 / np.pi) * forecast['windSpeed']
    forecast.drop(['summary', 'icon', 'windBearing', 'windSpeed', 'precipType'],
                  axis=1, inplace=True)
    forecast['time'] = pd.to_datetime(forecast['time'])
    forecast.sort_values('time', inplace=True)
    
    orig_cols = forecast.columns
    
    forecast_pivot = rd.process_hourly_data(forecast, beach_col_name='beach',
                                            timestamp_col_name='time', hours_offset=-15)
    forecast_pivot2 = rd.process_hourly_data(forecast, beach_col_name='beach',
                                             timestamp_col_name='time', hours_offset=-24)
    forecast_pivot2.drop([c for c in forecast_pivot2.columns if (c[-3] == '-' and int(c[-3:]) > -16)],
                          axis=1, inplace=True)
    forecast_pivot = pd.merge(forecast_pivot, forecast_pivot2)
    
    for days_offset in range(-10,-1):
        hours_offset = days_offset * 24
        
        forecast_pivot2 = rd.process_hourly_data(forecast, beach_col_name='beach',
                                                 timestamp_col_name='time',
                                                 hours_offset=hours_offset)
                                                 
        to_drop = [c for c in forecast_pivot2.columns if str(hours_offset) not in c]
        to_drop.remove('time')
        to_drop.remove('beach')
        
        forecast_pivot2.drop(to_drop, axis=1, inplace=True)
                              
        forecast_pivot = pd.merge(forecast_pivot, forecast_pivot2)
    
    df_cols = ['Escherichia.coli'] + \
        [str(n) + '_day_prior_Escherichia.coli' for n in historical_columns['Escherichia.coli']]
    forecast_pivot = pd.merge(forecast_pivot,
                              df[df_cols],
                              left_on=['time','beach'], right_on=['Full_date', 'Client.ID'])
    
    pca_filts = pca_filters(forecast_pivot, 235, orig_cols)


    ######################################################
    #### Process non-numeric columns
    ######################################################

    # process all of the nonnumeric columns
    # This method just assigns a numeric value to each possible value
    # of the non-numeric column. Note that this will not work well
    # for regression-style models, where instead dummy columns should
    # be created.
    def nonnumericCols(data, verbose=True):
        for f in data.columns:
            if data[f].dtype=='object':
                if (verbose):
                    print('Column ' + str(f) + ' being treated as non-numeric')
                lbl = sklearn.preprocessing.LabelEncoder()
                lbl.fit(list(data[f].values))
                data[f] = lbl.transform(list(data[f].values))
        return data

    df = nonnumericCols(df)


    ######################################################
    #### More NaN filling
    ######################################################

    # As a last NaN filling measure, we fill the NaNs of all columns
    # that are NOT the E. coli column with the mean value of the column,
    # the mean value taken over all data not from the same year as the
    # year of the row we are filling. For example, if there is a NaN
    # in the temperatureMax column in some row from 2010, then we will
    # fill that value with the mean temperatureMax value from all years
    # that are NOT 2010.
    cols = df.columns.tolist()
    cols.remove('Escherichia.coli')
    years = df['Full_date'].map(lambda x: x.year)
    for yr in years.unique():
        not_yr = np.array(years != yr)
        is_yr = np.array(years == yr)
        for col in cols:
            if df.ix[is_yr, col].isnull().sum() > df.shape[0] * 0.1:
                df.ix[is_yr, 'isnull_mean_filled_' + col] = df.ix[is_yr, col].isnull()
        df.ix[is_yr, cols] = df.ix[is_yr, cols].fillna(df.ix[not_yr, cols].mean())


    ######################################################
    #### Drop any rows that still have NA, set up outputs
    ######################################################

    # The following lines will print the % of rows that:
    #  (a) have a NaN value in some column other than Escherichia.coli, AND
    #  (b) the column Escherichia.coli is NOT NaN.
    # Since we are now filling NaNs with column averages above, this should
    # always report 0%. I'm leaving the check in here just to be sure, though.
    total_rows_predictors = df.dropna(subset=['Escherichia.coli'], axis=0).shape[0]
    nonnan_rows_predictors = df.dropna(axis=0).shape[0]
    print('Dropping {0:.4f}% of rows because predictors contain NANs'.format(
        100.0 - 100.0 * nonnan_rows_predictors / total_rows_predictors
    ))

    # Any rows that still have NaNs are NaN b/c there is no E. coli reading
    # We should drop these rows b/c there is nothing for us to predict.
    df.dropna(axis=0, inplace=True)
    
    predictors = df.drop(meta_columns, axis=1)
    meta_info = df[meta_columns]

    return predictors, meta_info


def pca_filters(df, T, original_cols,
                time_col='time',
                beach_col='beach',
                ecoli_col='ecoli'):
                    
    ### Compute PCA transforms
                    
    pcas = {}
    df_pcas = pd.DataFrame(index=df[time_col].unique())
    
    for c in df.columns:
        if c in [time_col, beach_col, ecoli_col]:
            continue
        # pivot the dataframe so that each row is a day
        pivoted = df.pivot(index='Full_date', columns='Client.ID', values=c)
        
        # remove any rows that have a NaN
        pivoted=pivoted[pivoted.notnull().all(axis=1)]
        
        # Compute the PCA, take first 6 components
        pca = sklearn.decomposition.PCA(n_components=6)
        pca_df = pd.DataFrame(pca.fit_transform(pivoted),
                              index=pivoted.index,
                              columns=[c + '_pca_component_' + n for n in '012345'])
                              
        # Merge in the new columns to the DataFrame of PCA components
        df_pcas = df_pcas.merge(pca_df, left_index=True, right_index=True, how='outer')
        pcas[c] = pca
    
    ### Compute difference in mean values, and ranksum p-values from hi vs. lo Ecoli    
    
    # pos_means is a dictionary keyed on beach names. Each value is itself a
    # dictionary keyed on the column names. These values indicate the mean
    # value of that column when E coli is elevated. Similarly for neg_means
    pos_means = {}
    neg_means = {}
    
    # rs_pvalues is a dictionary keyed in the same way as above. It's values
    # are the p-values resulting from rank-sum tests of differences between
    # values from high vs. low E. coli
    rs_pvalues = {}
    
    for b in df[beach_col].unique():
        pos_means[b] = {}
        neg_means[b] = {}
        rs_pvalues[b] = {}
        
        # subset on the beach
        beach_df = df[df[beach_col] == b]
        
        beach_df.set_index(time_col, inplace=True)
        
        beach_df = beach_df.merge(df_pcas, left_index=True, right_index=True, how='outer')
        
        above_thresh = beach_df[beach_df[ecoli_col] >= T]
        below_thresh = beach_df[beach_df[ecoli_col] < T]
        
        for c in df_pcas.columns:
            if c in [time_col, beach_col, ecoli_col]:
                continue
            
            pos_means[b][c] = above_thresh[c].mean()
            neg_means[b][c] = below_thresh[c].mean()
            
            rs_pvalues[b][c] = scipy.stats.ranksums(above_thresh[c], below_thresh[c]).pvalue
    
    
    ### Create actual predictor values
    
    preds = df[[beach_col, time_col]]
    
    for b in preds[beach_col].unique():
        beach_index = preds.index(preds[beach_col] == b)
        beach_times = preds.loc[preds[beach_col] == b, time_col]
        
        for orig_c in original_cols:
            if orig_c in [time_col, beach_col, ecoli_col]:
                continue
            preds[orig_c + '_pca_component_0'] = 0
            preds[orig_c + '_pca_component_1'] = 0
            preds[orig_c + '_pca_component_A'] = 0
            
            for c in df_pcas.columns:
                # pivoted columns in the input df are named as a super-string
                # of the non-pivoted versions.
                if not orig_c in c:
                    continue
                comp = '_pca_component_0'
                score = df_pcas.loc[beach_times, c + comp] - neg_means[b][c + comp]
                score = score * (pos_means[b][c + comp]-neg_means[b][c + comp])
                score = score * ((1 - rs_pvalues[b][c + comp])**100)
                preds.loc[beach_index[score.notnull()], c + comp] += score[score.notnull()].values
        
    return pcas, df_pcas, pos_means, neg_means, rs_pvalues


if __name__ == '__main__':
    # Command Line Argument parsing
    parser = argparse.ArgumentParser(description='Process beach data.')
    parser.add_argument('-i', '--input', type=str,
                        metavar='input_filename', help='input CSV filename')
    parser.add_argument('-v', '--verbose', action='count', default=0)

    args = parser.parse_args()

    # Load the data
    if args.input:
        df = pd.read_csv(args.input, parse_dates='Full_date')
        df['Full_date'] = rd.date_lookup(df['Full_date'])
    else:
        df = rd.read_data(read_weather_station=False, read_water_sensor=False)

    # Extract the EPA (technically USGS) model performance from the data
    epa_model_df = df[['Drek_Prediction', 'Escherichia.coli']].dropna()

    # Prepare the data
    predictors, meta_info = prepare_data(df)
    timestamps = meta_info['Full_date']
    classes = meta_info['Escherichia.coli'] > 235

    print('Using the following columns as predictors:')
    for c in predictors.columns:
        print('\t' + str(c))

    # Set up model parameters, these will be passed to the
    # classifier as keyword arguments
    hyperparams = {
        ## Parameters that effect computation
        'n_estimators':1000,
        'max_depth':5,
        'class_weight':{0: 1.0, 1: 7.0},
        'criterion':'entropy',
        ## Misc parameters
        'n_jobs':-1,
        'verbose':False
    }
    partial_auc_bounds = [0.005, 0.05]
    clfs, auc_rocs, roc_ax, pr_ax = model(timestamps, predictors, classes,
                                          classifier=sklearn.ensemble.RandomForestClassifier,
                                          hyperparams=hyperparams,
                                          roc_bounds=partial_auc_bounds,
                                          prediction_attribute='predict_proba',
                                          verbose=args.verbose)

    # Plotting
    ## ROC
    ### Make ROC yearly lines more transparent
    c = roc_ax.get_lines()
    for line in c:
        line.set_alpha(.7)

    ### Plot ROC curve for EPA model
    fpr, tpr, threshes, auc_roc = viz.roc(epa_model_df['Drek_Prediction'],
                                          epa_model_df['Escherichia.coli'] > 235,
                                          ax=roc_ax, block_show=False,
                                          bounds=partial_auc_bounds,
                                          mark_threshes=[235.0])
    ### Format the EPA line
    auc_roc = float(auc_roc)
    epa_line = roc_ax.get_lines()[-3]
    epa_line.set_color([0,0,0])
    epa_line.set_ls('--')
    epa_line.set_linewidth(3)
    epa_line.set_alpha(.85)
    epa_line.set_label('EPA Model - AUC: {0:.5f}'.format(auc_roc))
    roc_ax.get_lines()[-2].set_label('EPA Model @ 235.0')

    ### Prettify the axis
    roc_ax.legend(bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0.)
    roc_ax.set_aspect('auto')  # we are going to be zooming around, set it to auto
    roc_ax.grid(True, which='major')
    roc_ax.set_title('ROC - mean pAUC: {0:.7f} $\pm$ {1:.7f}'.format(
        np.mean(auc_rocs), np.std(auc_rocs)))
    roc_ax.set_ylim([0, .5])

    ## Precision-Recall curve
    ### Make PR yearly lines more transparent
    c = pr_ax.get_children()
    for line in c:
        line.set_alpha(.7)

    ### Plot PR curve for EPA model
    tpr, ppv, threshes, auc_pr = viz.precision_recall(epa_model_df['Drek_Prediction'],
                                                      epa_model_df['Escherichia.coli'] > 235,
                                                      ax=pr_ax, block_show=False)
    ### Format the EPA line
    auc_pr = float(auc_pr)
    epa_line = pr_ax.get_lines()[-2]
    epa_line.set_color([0,0,0])
    epa_line.set_ls('--')
    epa_line.set_linewidth(3)
    epa_line.set_alpha(.85)
    epa_line.set_label('EPA Model - AUC: {0:.5f}'.format(auc_pr))

    ### Plot an X where the current model is performing
    i = np.where(threshes < 235.0)[0][0]
    pr_ax.plot(tpr[i], ppv[i], 'xk', label='EPA model at 235',
               markersize=10.0, markeredgewidth=2.0)

    ### Prettify the axis
    pr_ax.legend(bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0.)
    pr_ax.grid(True, which='major')

    ## Update plots
    plt.draw()

    # Save PNGs of figures, and this code
    now = dt.datetime.now().isoformat().replace(':', '_').replace('.','_')

    roc_ax.get_figure().savefig(now + '--roc.png', format='png')
    pr_ax.get_figure().savefig(now + '--pr.png', format='png')
    os.system('git diff modeling.py > ' + now + '--patch.diff')


    plt.show(block=True)

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from datetime import datetime
from datetime import timedelta
import pytz
from dateutil.tz import tzutc

class BotDataSet:
    
    def __init__(self): 
        self.df = None

    def loadCSV(self, file_name, append=False):
        df = pd.read_csv(file_name, 
                         parse_dates=['SendDate', 'RequestDate'],
                        dtype = {'AS Number':str})  

        # Clean up
        df['AS Name'].fillna('Unknown', inplace=True)
        df['AS Number'].fillna('Unknown', inplace=True)
        df.loc[df['AS Number']=='Unknown','CIDR Range'] = 'Unknown'

        # Calculated Columns
        # SendRequestSeconds = RequestDate - SendDate - The numbe rof seconds after the send the request came in.
        df['SendRequestSeconds'] = ((pd.to_datetime(df['RequestDate']) - 
                                    pd.to_datetime(df['SendDate']))
                                        .dt.total_seconds()).clip(lower=0).astype('int')
        
        # Make natural log version of SendRequestSeconds
        # By adding e (np.exp(1)), the scale goes from 1 to ~15
        # 0 seconds would give a value of 1
        # 2 days (172800 seconds) would give a value of 14.77
        df['SendRequestSeconds_ln'] = np.log(df['SendRequestSeconds'] + np.exp(1)) 
        # ln(0) = -inf and ln(-x) is complex, so we need to do clean up and set these to 1
        df['SendRequestSeconds_ln'].replace([np.inf, -np.inf], np.nan, inplace=True)
        df['SendRequestSeconds_ln'].fillna(1, inplace=True)
        
        if self.df is not None and append:
            self.df = self.df.append(df)
        else:
            self.df = df
        
    def get_session_column(self, group_column_1, datetime_column, time_gap, session_column, group_column_2 = None):
        """
        This method returns a pandas series that holds "session id"

        df = The dataframe we will based the session on
        group_column_1 = The column name will we use to partition the data on
        datatime_column = The datetime column name we will use as the basis of the session
        time_gap = How long between sorted requests need to elapse before we create a new session
        session_column = The name we will give to the new session column
        group_column_2 (Optional) = A second column name we can use to partition the data on

        1) Make sue passed in df is indexed and sorted by the datatime column
        2) Build group list -  group = group_column_1 OR group = [group_column_1, group_column_2]
        3) Copy the necessary columns into a working dataframe
        4) Add a column that shows the last previous datetime for the partitioned data (NaT if no previous row)
        5) Add a column that determines if the current row is a new session (NaT or too big a gap in time)
        6) Add a column that uses cumsum() to create a LocalSessionID scoped to the partition
        7) Add a column that uses a hash to get a global SessionID
        8) Return just the series.  

        Because we make sure the passed in dataframe is sorted, 
            the index of the returned series matches the index of the passed in dataframe
        """
        
        df = self.df
        
        # The dataframe must be stored by RequestDate since we are window functions on this order 
        if not (df.index.name == datetime_column and df.index.is_monotonic()):
            df.sort_values(datetime_column, inplace=True)

        # set column names (this sorts the passed in dataframe)
        lastColumnName = 'Last' + datetime_column
        group = group_column_1
        if group_column_2:
            group = [group_column_1, group_column_2]

        # select local dataframe (allows us to work only on a subset of the full dataframe)
        if group_column_2:
            working_df = df[[group_column_1, datetime_column, group_column_2]].copy()
        else:
            working_df = df[[group_column_1, datetime_column]].copy()         


        # Create a pandas series (column) grouping by SendID that holds the previous RequestDate for that SendID
        last = working_df.groupby(group)[datetime_column].transform(lambda x:x.shift(1))

        # Append the above column to the dataframe with a name of LastRequestDate
        working_df = pd.concat([working_df, last.rename(lastColumnName)], axis=1)

        # It is a new session if LastRequestDate is null or the LastRequestDate is less then T old
        # We cast the result as an int so we can use cumsum in the next step
        working_df['IsNewSession'] = np.logical_or(working_df[datetime_column] - working_df[lastColumnName] > time_gap, 
                                           working_df[lastColumnName].isnull()).astype(int)

        # Use cumnsum to get the session number within a specific SendID. Note: This is not yet a global session id
        working_df['LocalSessionID'] = working_df.groupby(group)['IsNewSession'].cumsum()

        # New create a global session ID by combining the group by value and the LocalSessionID
        if group_column_2:
            working_df[session_column] = (
                                                working_df[group_column_1].astype(str) + '|' 
                                                + working_df[group_column_2].astype(str) + '|' 
                                                + working_df['LocalSessionID'].astype(str)
                                         ).apply(hash)
        else:
            working_df[session_column] =  (
                                                working_df[group_column_1].astype(str) + '|' 
                                                + working_df['LocalSessionID'].astype(str)
                                          ).apply(hash)

        return working_df[session_column]
    
    def loadSessionColumn(self, new_column_name, time_gap, group_column_1, group_column_2 = None):

        # Session based on just the InboxID
        self.df = pd.concat([self.df, 
                        self.get_session_column(
                                         group_column_1=group_column_1,  
                                         group_column_2=group_column_2,  
                                         datetime_column='RequestDate', 
                                         time_gap=time_gap, 
                                         session_column=new_column_name)], 
                        axis=1)

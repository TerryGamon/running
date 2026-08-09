import pandas as pd
import numpy as np
from datetime import date, datetime
from . import passiv_rlz 

def _to_date(val):
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        return pd.to_datetime(val).date()
    if isinstance(val, pd.Timestamp):
        return val.date()
    if isinstance(val, np.datetime64):
        return pd.Timestamp(val).date()
    raise TypeError(f"Unsupported date type: {type(val)}")

def _is_leap_year(year):
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)

def _days_in_period(d1, d2):
    # Returns 366.0 if the period contains February 29, otherwise 365.0
    for y in range(d1.year, d2.year + 1):
        try:
            leap_day = date(y, 2, 29)
            if d1 <= leap_day <= d2:
                return 366.0
        except ValueError:
            pass
    return 365.0

def get_coupon_dates_backward(maturity_date, issue_date, freq):
    """
    Generates regular coupon dates working backwards from maturity_date
    until we reach a date less than or equal to issue_date.
    """
    m_dt = pd.to_datetime(maturity_date)
    i_dt = pd.to_datetime(issue_date)
    f = int(freq)
    step_months = 12 // f
    
    dates = []
    curr = m_dt
    while curr > i_dt:
        dates.append(curr.date())
        curr = curr - pd.DateOffset(months=step_months)
    
    # curr is now <= issue_date. We append it as the previous regular coupon date before issue.
    dates.append(curr.date())
    dates.reverse()
    return dates

def generate_schedule(settlement_date, maturity_date, freq, first_coupon_type='regular', issue_date=None):
    """
    Generates the coupon schedule and payment amounts from the issue/settlement perspective.
    Returns:
        list of tuples: [(cf_date, cf_amount)]
        prev_coupon_date: the coupon date immediately preceding settlement_date
        next_coupon_date: the coupon date immediately following settlement_date
        first_coupon_amount: the amount of the first coupon
    """
    settlement = _to_date(settlement_date)
    maturity = _to_date(maturity_date)
    f = int(freq)
    
    # If first_coupon_type is irregular but issue_date is not provided, try to find it or default to regular
    if first_coupon_type in ['short', 'long'] and issue_date is None:
        raise ValueError("issue_date is required when first_coupon_type is 'short' or 'long'")
        
    if issue_date is None:
        issue = settlement # Fallback
    else:
        issue = _to_date(issue_date)
        
    # Generate regular dates backwards from maturity
    reg_dates = get_coupon_dates_backward(maturity, issue, f)
    
    # reg_dates contains: [R_k, R_{k-1}, ..., R_0] where R_k <= issue and R_0 = maturity.
    # The first regular coupon date after issue is reg_dates[1].
    # Let's find the first coupon date of the bond (T_first).
    if len(reg_dates) < 2:
        # Should not happen as maturity > issue
        reg_dates = [issue, maturity]
        
    first_reg_after_issue = reg_dates[1]
    
    if first_coupon_type == 'short':
        first_coupon_date = first_reg_after_issue
        coupon_schedule = [first_coupon_date] + reg_dates[2:]
        # Short first coupon is pro-rata: days from issue to first coupon
        days_in_first = (first_coupon_date - issue).days
        basis = _days_in_period(issue, first_coupon_date)
        first_coupon_amount = days_in_first / basis  # Fractional coupon amount
    elif first_coupon_type == 'long':
        if len(reg_dates) < 3:
            # If the bond maturity is too short to skip a coupon, fallback to short
            first_coupon_date = first_reg_after_issue
            coupon_schedule = [first_coupon_date] + reg_dates[2:]
            days_in_first = (first_coupon_date - issue).days
            basis = _days_in_period(issue, first_coupon_date)
            first_coupon_amount = days_in_first / basis
        else:
            first_coupon_date = reg_dates[2]
            coupon_schedule = [first_coupon_date] + reg_dates[3:]
            days_in_first = (first_coupon_date - issue).days
            basis = _days_in_period(issue, first_coupon_date)
            first_coupon_amount = days_in_first / basis
    else: # regular
        # If regular, we just use the regular schedule
        # prev regular coupon date before issue is reg_dates[0] (which is <= issue)
        first_coupon_date = first_reg_after_issue
        coupon_schedule = reg_dates[1:]
        first_coupon_amount = 1.0 / f
        
    return coupon_schedule, issue, first_coupon_date, first_coupon_amount

def calculate_macaulay_duration(settlement_date, maturity_date, coupon, yld, freq, 
                               first_coupon_type='regular', issue_date=None, 
                               discount_method='standard', compounding='annual', runden=5):
    """
    Calculates the Macaulay duration of a bond.
    
    Parameters:
        settlement_date (str/date/Timestamp): Settlement date.
        maturity_date (str/date/Timestamp): Maturity date.
        coupon (float): Annual coupon rate as decimal (e.g. 0.05 for 5%).
        yld (float): Yield-to-maturity as decimal (e.g. 0.03 for 3%).
        freq (int): Coupon frequency (1, 2, 4, 12).
        first_coupon_type (str): 'regular', 'short', or 'long'.
        issue_date (str/date/Timestamp): Issue date (required for short/long coupons).
        discount_method (str): 
            - 'standard': Discounting based on regular coupon periods (w + i - 1).
            - 'anniversary': Discounting based on year fraction from passiv_rlz anniversary method.
            
    Returns:
        float: Macaulay Duration in years.
    """
    settlement = _to_date(settlement_date)
    maturity = _to_date(maturity_date)
    
    if settlement >= maturity:
        raise ValueError("settlement_date must be before maturity_date")
        
    coupon_schedule, issue, first_coupon_date, first_coupon_amount_pct = generate_schedule(
        settlement, maturity, freq, first_coupon_type, issue_date
    )
    
    # Filter for future cash flows (dates > settlement)
    future_dates = [d for d in coupon_schedule if d > settlement]
    
    if not future_dates:
        # No cash flows left
        if runden is not None:
            return round(0.0, runden), round(0.0, runden)
        return 0.0, 0.0
        
    # Generate coupon amounts
    # If the first coupon date is in the future, its amount might be irregular (short/long)
    cfs = []
    
    for idx, d in enumerate(future_dates):
        is_last = (d == maturity)
        
        # Determine coupon amount for this date (coupon is in percent, e.g. 3.0)
        if d == first_coupon_date and first_coupon_type in ['short', 'long']:
            # The first coupon of the bond is in the future, so it is irregular
            cf_val = coupon * first_coupon_amount_pct
        else:
            cf_val = coupon / freq
            
        if is_last:
            cf_val += 100.0
            
        cfs.append(cf_val)
        
    # Calculate cash flow times (t_i) in years
    t = []
    
    if discount_method == 'standard':
        # Standard bond discounting: w + i - 1 periods
        # Find previous and next coupon dates around settlement
        # If settlement is before the first coupon date:
        if settlement < first_coupon_date:
            # Settlement is in the first coupon period
            next_cp = first_coupon_date
            
            # Find the regular pseudo-period containing settlement by going backwards
            # from first_coupon_date in regular coupon intervals (12//freq months).
            curr = next_cp
            while True:
                prev = pd.to_datetime(curr) - pd.DateOffset(months=12//freq)
                prev = prev.date()
                if prev <= settlement:
                    prev_cp = prev
                    break
                curr = prev
                
            period_days = (curr - prev_cp).days
            w = (curr - settlement).days / period_days / freq
            
            # Count steps from curr to next_cp
            steps = 0
            temp = curr
            while temp < next_cp:
                temp = (pd.to_datetime(temp) + pd.DateOffset(months=12//freq)).date()
                steps += 1
                
            t_first = w + steps / freq
            for idx in range(len(future_dates)):
                t.append(t_first + idx / freq)
        else:
            # Settlement is after the first coupon date
            # All future cash flows are regular.
            curr = first_coupon_date
            while True:
                nxt = pd.to_datetime(curr) + pd.DateOffset(months=12//freq)
                nxt = nxt.date()
                if curr <= settlement < nxt:
                    prev_cp = curr
                    next_cp = nxt
                    break
                curr = nxt
                
            period_days = (next_cp - prev_cp).days
            days_to_next = (next_cp - settlement).days
            w = (days_to_next / period_days) / freq
            
            for idx in range(len(future_dates)):
                t.append(w + idx / freq)
                
    elif discount_method == 'anniversary':
        # Discounting based on year fraction from passiv_rlz anniversary method
        for d in future_dates:
            t_val = passiv_rlz.get_year_fraction_anniversary(settlement, d, freq=freq)
            t.append(t_val)
    else:
        raise ValueError(f"Unknown discount_method: {discount_method}")
        
    # Convert yield from percent to decimal for calculations
    y = yld / 100.0
    
    # Calculate present value (PV) and weighted PV
    pvs = []
    weighted_pvs = []
    
    for cf, time in zip(cfs, t):
        # Discounting factor
        if compounding == 'periodic':
            df_val = (1 + y / freq) ** (-time * freq)
        elif compounding == 'annual':
            df_val = (1 + y) ** (-time)
        elif compounding == 'continuous':
            df_val = np.exp(-y * time)
        else:
            raise ValueError(f"Unknown compounding method: {compounding}")
            
        pv = cf * df_val
        pvs.append(pv)
        weighted_pvs.append(time * pv)
        
    pv_total = sum(pvs)
    if pv_total == 0:
        if runden is not None:
            return round(0.0, runden), round(0.0, runden)
        return 0.0, 0.0
        
    mac_dur = sum(weighted_pvs) / pv_total
    
    # Calculate Clean Price: Dirty Price (pv_total) - Accrued Interest
    acc_int = calculate_accrued_interest(settlement, maturity, coupon, freq, first_coupon_type, issue_date)
    clean_price = pv_total - acc_int
    
    if runden is not None:
        return round(mac_dur, runden), round(clean_price, runden)
    return mac_dur, clean_price

def calculate_modified_duration(settlement_date, maturity_date, coupon, yld, freq, 
                               first_coupon_type='regular', issue_date=None, 
                               discount_method='standard', compounding='annual', runden=5):
    """
    Calculates the Modified duration of a bond.
    """
    mac_dur, clean_price = calculate_macaulay_duration(
        settlement_date, maturity_date, coupon, yld, freq, 
        first_coupon_type, issue_date, discount_method, compounding, runden=None
    )
    y = yld / 100.0
    if compounding == 'periodic':
        mod_dur = mac_dur / (1 + y / freq)
    elif compounding == 'annual':
        mod_dur = mac_dur / (1 + y)
    elif compounding == 'continuous':
        mod_dur = mac_dur
    else:
        raise ValueError(f"Unknown compounding method: {compounding}")
        
    if runden is not None:
        return round(mod_dur, runden), round(clean_price, runden)
    return mod_dur, clean_price

def get_coupon_period_dates(settlement_date, maturity_date, freq, 
                            first_coupon_type='regular', issue_date=None):
    """
    Returns the previous and next coupon dates surrounding the settlement_date.
    
    Parameters:
        settlement_date (str/date/Timestamp): Settlement date.
        maturity_date (str/date/Timestamp): Maturity date.
        freq (int): Coupon frequency (1, 2, 4, 12).
        first_coupon_type (str): 'regular', 'short', or 'long'.
        issue_date (str/date/Timestamp): Issue date.
        
    Returns:
        tuple: (prev_coupon_date, next_coupon_date) as datetime.date objects.
    """
    settlement = _to_date(settlement_date)
    maturity = _to_date(maturity_date)
    f = int(freq)
    
    coupon_schedule, issue, first_coupon_date, _ = generate_schedule(
        settlement, maturity, freq, first_coupon_type, issue_date
    )
    
    if settlement >= maturity:
        next_cp = maturity
        prev_cp = coupon_schedule[-2] if len(coupon_schedule) > 1 else issue
        return prev_cp, next_cp
        
    future_dates = [d for d in coupon_schedule if d > settlement]
    if not future_dates:
        return None, None
    next_cp = future_dates[0]
    
    if next_cp == first_coupon_date:
        if first_coupon_type in ['short', 'long']:
            prev_cp = issue
        else:
            prev_cp = pd.to_datetime(next_cp) - pd.DateOffset(months=12//f)
            prev_cp = prev_cp.date()
    else:
        idx = coupon_schedule.index(next_cp)
        prev_cp = coupon_schedule[idx - 1]
        
    return prev_cp, next_cp

def calculate_accrued_interest(settlement_date, maturity_date, coupon, freq,
                              first_coupon_type='regular', issue_date=None):
    """
    Calculates the accrued interest of a bond.
    Returns the accrued interest as percentage of face value (100).
    """
    settlement = _to_date(settlement_date)
    maturity = _to_date(maturity_date)
    f = int(freq)
    
    if settlement >= maturity:
        return 0.0
        
    prev_cp, next_cp = get_coupon_period_dates(settlement, maturity, freq, first_coupon_type, issue_date)
    
    if prev_cp is None or next_cp is None:
        return 0.0
        
    # Check if settlement is in the irregular first coupon period
    coupon_schedule, issue, first_coupon_date, _ = generate_schedule(
        settlement, maturity, freq, first_coupon_type, issue_date
    )
    
    if next_cp == first_coupon_date and first_coupon_type in ['short', 'long']:
        # Settlement is in the first coupon period (irregular)
        days_accrued = (settlement - issue).days
        basis = _days_in_period(issue, first_coupon_date)
        acc_int = coupon * (days_accrued / basis)
    else:
        period_days = (next_cp - prev_cp).days
        days_accrued = (settlement - prev_cp).days
        acc_int = (coupon / f) * (days_accrued / period_days)
        
    return acc_int

def deduce_coupon_type(settlement_date, maturity_date, coupon, yld, freq, 
                       target_mac_dur=None, target_price=None, issue_date=None, 
                       discount_method='standard', compounding='annual'):
    """
    Deduces the coupon type ('regular', 'short', or 'long') by recalculating
    the Macaulay duration or Clean Price under all three assumptions and choosing the one
    that yields the smallest absolute error compared to target_mac_dur or target_price.
    
    Parameters:
        settlement_date (str/date/Timestamp): Settlement date.
        maturity_date (str/date/Timestamp): Maturity date.
        coupon (float): Annual coupon rate as decimal.
        yld (float): Yield-to-maturity as decimal.
        freq (int): Coupon frequency (1, 2, 4, 12).
        target_mac_dur (float): Target Macaulay Duration to match.
        target_price (float): Target Clean Price to match.
        issue_date (str/date/Timestamp): Issue date.
        discount_method (str): 'standard' or 'anniversary'.
        compounding (str): 'periodic', 'annual', or 'continuous'.
        
    Returns:
        str: 'regular', 'short', or 'long'
    """
    types = ['regular']
    if issue_date is not None:
        types.extend(['short', 'long'])
        
    best_type = None
    min_error = float('inf')
    
    for t in types:
        try:
            mac_dur, clean_price = calculate_macaulay_duration(
                settlement_date, maturity_date, coupon, yld, freq, 
                first_coupon_type=t, issue_date=issue_date, 
                discount_method=discount_method, compounding=compounding, runden=None
            )
            
            error = 0.0
            if target_mac_dur is not None:
                error += abs(mac_dur - target_mac_dur)
            if target_price is not None:
                error += abs(clean_price - target_price)
                
            if error < min_error:
                min_error = error
                best_type = t
        except Exception:
            pass
            
    return best_type




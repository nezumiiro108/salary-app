import streamlit as st
import datetime
import math
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from decimal import Decimal, ROUND_FLOOR, getcontext
import calendar

# Decimalの計算精度を高く設定
getcontext().prec = 30

# --- 1. ページ設定 ---
st.set_page_config(page_title="給料帳", layout="centered")

# --- 2. デザイン ---
st.markdown("""
    <style>
    /* 全体の背景をダークに固定 */
    .stApp { background-color: #0e1117; color: #fafafa; }
    .block-container { padding-top: 2rem; padding-bottom: 5rem; max_width: 600px; }
    
    /* カレンダー */
    .calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; margin-top: 5px; }
    .cal-header { text-align: center; font-size: 10px; font-weight: bold; color: #aaa; padding-bottom: 2px; }
    .cal-day { background-color: #262730; border: 1px solid #333; border-radius: 4px; height: 50px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
    .cal-num { font-size: 10px; color: #ccc; margin: 0; line-height: 1.2; }
    .cal-pay { font-size: 8.5px; font-weight: bold; color: #4da6ff; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max_width: 100%; padding: 0 2px; }
    .cal-today { border: 1px solid #4da6ff; background-color: #1e2a3a; }
    .cal-empty { background-color: transparent; border: none; }
    
    /* 合計エリア */
    .total-area { text-align: center; padding: 10px; background-color: #262730; border-radius: 8px; border: 1px solid #444; color: #fff; margin-bottom: 15px; }
    .total-amount { font-size: 22px; font-weight: bold; color: #4da6ff; }
    .total-sub { font-size: 10px; color: #aaa; }
    
    /* 履歴リスト */
    .history-row { padding: 6px 0; display: flex; justify-content: space-between; align-items: center; color: #eee; border-bottom: 1px solid #333; }
    .tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-right: 5px; font-weight: normal; display: inline-block; }
    .tag-work { background: #1c3a5e; color: #aaddff; }
    .tag-break { background: #4a1a1a; color: #ffaaaa; }
    .tag-drive { background: #1a4a3a; color: #aaffdd; }
    .tag-direct { background: #5e4a1c; color: #ffddaa; border: 1px solid #cc9900; }
    .tag-other { background: #444444; color: #dddddd; border: 1px solid #666; }
    .tag-plus { color: #aaddff; font-weight: bold; }
    .tag-minus { color: #ffaaaa; font-weight: bold; }

    .stSlider { padding-bottom: 10px !important; }
    .stSlider label { font-size: 12px; color: #ddd !important; }
    
    div[data-testid="column"] button { float: right; }
    </style>
""", unsafe_allow_html=True)

# --- 3. Google Sheets 接続 ---
conn = st.connection("gsheets", type=GSheetsConnection)

def get_all_records_df():
    try:
        df = conn.read(worksheet="records", ttl=600)
        df = df.fillna(0)
        df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
        df['date_str'] = df['date_str'].astype(str)
        return df
    except Exception:
        return pd.DataFrame(columns=['id', 'date_str', 'type', 'start_h', 'start_m', 'end_h', 'end_m', 'distance_km', 'pay_amount', 'duration_minutes'])

def save_record_to_sheet(new_record_dict):
    with st.spinner("保存中..."):
        df = get_all_records_df()
        new_id = 1
        if not df.empty and 'id' in df.columns:
            if df['id'].max() > 0: new_id = df['id'].max() + 1
        new_record_dict['id'] = new_id
        new_row = pd.DataFrame([new_record_dict])
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="records", data=updated_df)
        st.cache_data.clear()

def delete_record_from_sheet(record_id):
    with st.spinner("削除中..."):
        df = get_all_records_df()
        if not df.empty:
            updated_df = df[df['id'] != record_id]
            conn.update(worksheet="records", data=updated_df)
            st.cache_data.clear()

def get_records_by_date(date_str):
    df = get_all_records_df()
    if df.empty: return []
    filtered = df[df['date_str'] == date_str].copy()
    return filtered.to_dict('records')

def get_min_record_date():
    df = get_all_records_df()
    if df.empty: return datetime.date.today()
    try:
        min_date_str = df['date_str'].min()
        return datetime.datetime.strptime(min_date_str, '%Y-%m-%d').date()
    except:
        return datetime.date.today()

def load_setting(key, default_value):
    try:
        df = conn.read(worksheet="settings", ttl=3600)
        if df.empty: return default_value
        row = df[df['key'] == key]
        if not row.empty: return row.iloc[0]['value']
        return default_value
    except:
        return default_value

def save_setting(key, value):
    with st.spinner("設定保存中..."):
        try:
            df = conn.read(worksheet="settings", ttl=0)
        except:
            df = pd.DataFrame(columns=['key', 'value'])
        if key in df['key'].values:
            df.loc[df['key'] == key, 'value'] = str(value)
        else:
            new_row = pd.DataFrame([{'key': key, 'value': str(value)}])
            df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="settings", data=df)
        st.cache_data.clear()

# --- 4. 計算ロジック ---
NIGHT_START = 22 * 60
NIGHT_END = 27 * 60
OVERTIME_THRESHOLD = 8 * 60

def calculate_driving_allowance(km):
    km = int(km)
    if km == 0: return 0
    if km < 10: return 150
    if km >= 340: return 3300
    return 300 + (math.floor((km - 10) / 30) * 300)

def calculate_direct_drive_pay(km):
    return int(km) * 25

def calculate_daily_total(records, base_wage, drive_wage):
    
    base_wage_dec = Decimal(base_wage)
    drive_wage_dec = Decimal(drive_wage)
    
    timeline = [None] * (48 * 60)
    fixed_pay = Decimal(0)
    
    sorted_records = sorted(records, key=lambda x: int(x['start_h']) * 60 + int(x['start_m']))
    
    for r in sorted_records:
        try:
            sh, sm = int(float(r['start_h'])), int(float(r['start_m']))
            eh, em = int(float(r['end_h'])), int(float(r['end_m']))
            dist = Decimal(r['distance_km'])
        except (ValueError, TypeError):
            continue
        
        if r['type'] == 'OTHER': fixed_pay += Decimal(r['pay_amount']); continue
            
        if r['type'] == 'DRIVE_DIRECT': fixed_pay += Decimal(calculate_direct_drive_pay(dist)); continue
            
        if r['type'] == 'DRIVE':
            fixed_pay += Decimal(calculate_driving_allowance(dist))
            activity = 'DRIVE'
        elif r['type'] == 'WORK':
            activity = 'WORK'
        elif r['type'] == 'BREAK':
            activity = 'BREAK'
        else: continue
            
        s_min = sh * 60 + sm
        e_min = eh * 60 + em
        for m in range(s_min, e_min):
            if m < len(timeline):
                timeline[m] = activity

    total_wage_points = Decimal(0)
    accumulated_work_minutes = 0
    
    for i in range(len(timeline)):
        act = timeline[i]
        if act not in ['WORK', 'DRIVE']: continue
            
        base_rate = drive_wage_dec if act == 'DRIVE' else base_wage_dec
        
        multiplier = Decimal(1)
        is_night = (NIGHT_START <= i < NIGHT_END)
        is_overtime = (accumulated_work_minutes >= OVERTIME_THRESHOLD)
        
        if is_night and is_overtime:
            multiplier = Decimal('1.5625') 
        elif is_night or is_overtime:
            multiplier = Decimal('1.25')
            
        total_wage_points += base_rate * multiplier
        accumulated_work_minutes += 1
    
    total_work_pay_dec = (total_wage_points / Decimal(60))
    final_work_pay = total_work_pay_dec.to_integral_value(rounding=ROUND_FLOOR)
    
    grand_total_dec = final_work_pay + fixed_pay
    
    return int(grand_total_dec), accumulated_work_minutes

def format_time_label(h, m):
    prefix = "翌" if h >= 24 else ""
    disp_h = h - 24 if h >= 24 else h
    return f"{prefix}{disp_h:02}:{m:02}"

# --- 5. セッション ---
# ★セッション初期化
if 'base_wage' not in st.session_state:
    try:
        loaded = load_setting('base_wage', '1190')
        st.session_state.base_wage = int(float(loaded))
    except:
        st.session_state.base_wage = 1190
if 'wage_drive' not in st.session_state:
    try:
        loaded_d = load_setting('wage_drive', '1050')
        st.session_state.wage_drive = int(float(loaded_d))
    except:
        st.session_state.wage_drive = 1050
if 'closing_day' not in st.session_state: # ★締め日初期化
    try:
        loaded_c = load_setting('closing_day', '31')
        st.session_state.closing_day = int(float(loaded_c))
    except:
        st.session_state.closing_day = 31


today = datetime.date.today()
if 'view_year' not in st.session_state: st.session_state.view_year = today.year
if 'view_month' not in st.session_state: st.session_state.view_month = today.month


def change_month(amount):
    m = st.session_state.view_month + amount
    y = st.session_state.view_year
    if m > 12: m = 1; y += 1
    elif m < 1: m = 12; y -= 1
    st.session_state.view_month = m
    st.session_state.view_year = y

def get_calendar_summary(wage_w, wage_d):
    df = get_all_records_df()
    if df.empty: return {}
    summary = {}
    unique_dates = df['date_str'].unique()
    for d in unique_dates:
        day_df = df[df['date_str'] == d]
        records = day_df.to_dict('records')
        pay, mins = calculate_daily_total(records, wage_w, wage_d) 
        summary[d] = {'pay': pay, 'min': mins}
    return summary

# ★ナビゲーションに必要な計算を独立した関数として定義
def get_period_dates(view_year, view_month, closing_day):
    Y, M, D = view_year, view_month, closing_day
    
    if D == 31:
        e_date = datetime.date(Y, M, calendar.monthrange(Y, M)[1])
        s_date = datetime.date(Y, M, 1)
        range_label = f"{Y}年{M}月1日～{e_date.day}日 (カレンダー月)"
    else:
        D_eff = min(D, calendar.monthrange(Y, M)[1])
        e_date = datetime.date(Y, M, D_eff)
        
        prev_M = M - 1
        prev_Y = Y
        if prev_M == 0: prev_M = 12; prev_Y = Y - 1
            
        s_day = D + 1
        max_day_prev = calendar.monthrange(prev_Y, prev_M)[1]
        s_day_eff = min(s_day, max_day_prev) 
        
        s_date = datetime.date(prev_Y, prev_M, s_day_eff)
        range_label = f"{prev_Y}年{prev_M}月{s_date.day}日～{Y}年{M}月{e_date.day}日 ({D}日締め)"
        
    return s_date, e_date, range_label

# --- 6. メイン表示 ---
tab_input, tab_calendar, tab_setting = st.tabs(["日次入力", "カレンダー", "設定"])

# ==========================================
# TAB: 設定
# ==========================================
with tab_setting:
    st.write("")
    st.subheader("設定")
    c1, c2, c3 = st.columns(3)
    new_wage = c1.number_input("基本時給 (円)", value=st.session_state.base_wage, step=10)
    new_drive_wage = c2.number_input("運転時給 (円)", value=st.session_state.wage_drive, step=10)
    new_closing_day = c3.number_input("締め日 (日)", value=st.session_state.closing_day, min_value=1, max_value=31, step=1, help="20日締めの場合は20を入力。月末締めの場合は31を入力。")

    if st.button("保存"):
        st.session_state.base_wage = new_wage
        st.session_state.wage_drive = new_drive_wage
        st.session_state.closing_day = new_closing_day
        save_setting('base_wage', new_wage)
        save_setting('wage_drive', new_drive_wage)
        save_setting('closing_day', new_closing_day)
        st.success("保存しました")
        st.rerun()
    
    st.markdown("""
    <div style='font-size:12px; color:#aaa; margin-top:10px;'>
    ・日中: 基本給<br>
    ・夜勤 (22:00-27:00): 1.25倍<br>
    ・残業 (8時間超): 1.25倍<br>
    ・運転手当: 距離に応じて加算<br>
    ・直行直帰: 25円/km (時給なし)
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# TAB: 日次入力
# ==========================================
with tab_input:
    st.write("")
    
    input_date = st.date_input("日付", value=datetime.date.today())
    input_date_str = input_date.strftime("%Y-%m-%d")
    
    st.markdown("---")
    record_type = st.radio("タイプ", ["勤務", "休憩", "運転", "その他"], horizontal=True, label_visibility="collapsed")
    
    def time_sliders(label, kh, km, dh, dm, disabled=False):
        curr_h = st.session_state.get(kh, dh)
        curr_m = st.session_state.get(km, dm)
        title_color = "#aaa" if not disabled else "#555"
        val_color = "#4da6ff" if not disabled else "#555"
        
        st.markdown(f"<div style='font-size:11px; font-weight:bold; color:{title_color};'>{label}: <span style='color:{val_color};'>{format_time_label(curr_h, curr_m)}</span></div>", unsafe_allow_html=True)
        c1, c2 = st.columns([1.3, 1])
        with c1: vh = st.slider("時", 0, 33, dh, key=kh, label_visibility="collapsed", disabled=disabled)
        with c2: vm = st.slider("分", 0, 59, dm, key=km, step=1, label_visibility="collapsed", disabled=disabled)
        return vh, vm

    if "その他" in record_type:
        st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)
        c_type, c_amt = st.columns([1, 1.5])
        with c_type:
            other_kind = st.radio("区分", ["支給 (+)", "控除 (-)"], label_visibility="collapsed")
        with c_amt:
            other_amount = st.number_input("金額 (円)", min_value=0, step=100)
        
        st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)
        if st.button("その他を追加", type="primary", use_container_width=True):
            if other_amount <= 0:
                st.error("金額を入力してください")
            else:
                final_pay = other_amount if "支給" in other_kind else -other_amount
                new_data = {
                    "date_str": input_date_str, "type": "OTHER",
                    "start_h": 0, "start_m": 0, "end_h": 0, "end_m": 0,
                    "distance_km": 0, "pay_amount": final_pay, "duration_minutes": 0
                }
                save_record_to_sheet(new_data)
                st.rerun()

    else:
        is_drive = "運転" in record_type
        is_direct = False
        
        if is_drive:
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
            is_direct = st.toggle("直行直帰 (時給なし・25円/km)", value=False)
        
        time_disabled = is_direct and is_drive

        sh, sm = time_sliders("開始", "sh_in", "sm_in", 9, 0, disabled=time_disabled)
        eh, em = time_sliders("終了", "eh_in", "em_in", 18, 0, disabled=time_disabled)
        
        dist_km = 0
        
        if is_drive:
            curr_km = int(st.session_state.get('d_km', 0))
            
            if is_direct:
                curr_allowance = calculate_direct_drive_pay(curr_km)
                lbl_color = "#ffddaa"
                lbl_text = "支給"
            else:
                curr_allowance = calculate_driving_allowance(curr_km)
                lbl_color = "#55bb88"
                lbl_text = "手当"

            st.markdown(f"""
                <div style='display:flex; justify-content:space-between; align-items:end; margin-bottom:2px;'>
                    <div style='font-size:11px; font-weight:bold; color:{lbl_color};'>距離: {curr_km} km</div>
                    <div style='font-size:11px; font-weight:bold; color:{lbl_color};'>{lbl_text}: ¥{curr_allowance:,}</div>
                </div>
            """, unsafe_allow_html=True)
            dist_km = st.slider("km", 0, 350, 0, 1, key="d_km", label_visibility="collapsed")
        
        st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)
        
        if st.button("追加", type="primary", use_container_width=True):
            if not time_disabled and (sh*60+sm) >= (eh*60+em):
                st.error("開始 < 終了 にしてください")
            else:
                if "運転" in record_type:
                    r_code = "DRIVE_DIRECT" if is_direct else "DRIVE"
                elif "休憩" in record_type:
                    r_code = "BREAK"
                else:
                    r_code = "WORK"
                
                save_sh, save_sm = (0, 0) if time_disabled else (sh, sm)
                save_eh, save_em = (0, 0) if time_disabled else (eh, em)
                
                new_data = {
                    "date_str": input_date_str, "type": r_code,
                    "start_h": save_sh, "start_m": save_sm, "end_h": save_eh, "end_m": save_em,
                    "distance_km": dist_km, "pay_amount": 0, 
                    "duration_minutes": (save_eh*60+save_em) - (save_sh*60+save_sm)
                }
                save_record_to_sheet(new_data)
                st.rerun()
            
    # === 登録済みリスト ===
    
    day_recs = get_records_by_date(input_date_str)
    day_pay, day_min = calculate_daily_total(day_recs, st.session_state.base_wage, st.session_state.wage_drive)

    st.markdown("<div style='font-size:12px; font-weight:bold; color:#888; margin-top:20px; margin-bottom:5px;'>登録済みリスト</div>", unsafe_allow_html=True)
    
    if not day_recs:
        st.caption("なし")
    else:
        for r in day_recs:
            c1, c2 = st.columns([0.85, 0.15]) 
            with c1:
                if r['type'] == "OTHER":
                    amt = int(r['pay_amount'])
                    tag_cls, tag_txt = "tag-other", "その他"
                    desc = f"<span class='tag-plus'>+¥{amt:,}</span>" if amt>=0 else f"<span class='tag-minus'>-¥{abs(amt):,}</span>"
                    html = f"<div class='history-row'><div><span class='tag {tag_cls}'>{tag_txt}</span></div><div style='font-size:12px;'>{desc}</div></div>"
                
                else:
                    s_h, s_m = int(r['start_h']), int(r['start_m'])
                    e_h, e_m = int(r['end_h']), int(r['end_m'])
                    time_str = f"{format_time_label(s_h, s_m)} ~ {format_time_label(e_h, e_m)}"
                    
                    if r['type'] == "DRIVE_DIRECT":
                        dist = int(float(r['distance_km']))
                        pay = calculate_direct_drive_pay(dist)
                        tag_cls, tag_txt = "tag-direct", "直行直帰"
                        info_txt = f"<span style='color:#ffddaa; font-size:10px;'>{dist}km / ¥{pay:,}</span>"
                    elif r['type'] == "DRIVE":
                        dist = int(float(r['distance_km']))
                        pay = calculate_driving_allowance(dist)
                        tag_cls, tag_txt = "tag-drive", "運転"
                        info_txt = f"{time_str} <span style='color:#aaffdd; font-size:10px;'>({dist}km/¥{pay:,})</span>"
                    elif r['type'] == "BREAK":
                        tag_cls, tag_txt = "tag-break", "休憩"
                        info_txt = time_str
                    else:
                        tag_cls, tag_txt = "tag-work", "勤務"
                        info_txt = time_str
                    
                    html = f"<div class='history-row'><div><span class='tag {tag_cls}'>{tag_txt}</span> <span style='font-size:12px;'>{info_txt}</span></div></div>"
                
                st.markdown(html, unsafe_allow_html=True)
                
            with c2:
                st.markdown('<div style="height: 4px;"></div>', unsafe_allow_html=True)
                if st.button("✕", key=f"del_{r['id']}"):
                    delete_record_from_sheet(r['id'])
                    st.rerun()
        
        st.markdown(f"""
            <div class="total-area" style="margin-top:10px; background-color:#1f2933;">
                <div class="total-sub">実働 {day_min//60}時間{day_min%60}分</div>
                <div class="total-amount">計 ¥{day_pay:,}</div>
            </div>
        """, unsafe_allow_html=True)

# ==========================================
# TAB: カレンダー
# ==========================================
with tab_calendar:
    min_rec = get_min_record_date()
    min_lim = min_rec.replace(day=1)
    current_dt = datetime.date.today()
    max_lim = current_dt.replace(day=1)
    view_d = datetime.date(st.session_state.view_year, st.session_state.view_month, 1)
    
    can_go_prev = view_d > min_lim
    can_go_next = view_d < max_lim

    c1, c2, c3 = st.columns([1, 3, 1])
    with c1: 
        if st.button("◀", use_container_width=True, disabled=not can_go_prev): 
            change_month(-1); st.rerun()
    with c2:
        # ★修正箇所: 「締め」を削除
        st.markdown(f"<div style='text-align:center; font-weight:bold; padding-top:5px; color:#bbb;'>{st.session_state.view_year}年 {st.session_state.view_month}月</div>", unsafe_allow_html=True)
    with c3:
        if st.button("▶", use_container_width=True, disabled=not can_go_next): 
            change_month(1); st.rerun()
    
    st.write("")
    summary = get_calendar_summary(st.session_state.base_wage, st.session_state.wage_drive)
    
    total_pay = 0
    total_min = 0
    s_date, e_date, range_label = get_period_dates(st.session_state.view_year, st.session_state.view_month, st.session_state.closing_day)
    
    curr = s_date
    while curr <= e_date:
        d_str = curr.strftime("%Y-%m-%d")
        if d_str in summary:
            total_pay += summary[d_str]['pay']
            total_min += summary[d_str]['min']
        curr += datetime.timedelta(days=1)

    st.markdown(f"""
    <div class="total-area">
        <div class="total-sub">計算期間: {range_label}</div>
        <div class="total-amount">¥ {total_pay:,}</div>
        <div class="total-sub" style="margin-top:5px;">総稼働: {total_min//60}時間{total_min%60}分</div>
    </div>
    """, unsafe_allow_html=True)

    html_parts = []
    for w in ["日", "月", "火", "水", "木", "金", "土"]:
        color = "#ff6666" if w=="日" else "#4da6ff" if w=="土" else "#aaa"
        html_parts.append(f'<div class="cal-header" style="color:{color}">{w}</div>')
    
    cal_obj = calendar.Calendar(firstweekday=6)
    month_days = cal_obj.monthdayscalendar(st.session_state.view_year, st.session_state.view_month)
    today_d = datetime.date.today()

    cal_html_parts = []
    cal_html_parts.append('<div class="calendar-grid">')
    cal_html_parts.extend(html_parts)
    
    for week in month_days:
        for day in week:
            if day == 0:
                cal_html_parts.append('<div class="cal-day cal-empty"></div>')
            else:
                curr_d = datetime.date(st.session_state.view_year, st.session_state.view_month, day)
                d_str = curr_d.strftime("%Y-%m-%d")
                pay_val = summary.get(d_str, {'pay': 0})['pay']
                
                extra_cls = "cal-today" if curr_d == today_d else ""
                pay_disp = f"¥{pay_val:,}" if pay_val > 0 else ""
                pay_div = f'<div class="cal-pay">{pay_disp}</div>' if pay_disp else ""
                
                cal_html_parts.append(f'<div class="cal-day {extra_cls}"><div class="cal-num">{day}</div>{pay_div}</div>')
                
    cal_html_parts.append('</div>') 
    st.markdown("".join(cal_html_parts), unsafe_allow_html=True)
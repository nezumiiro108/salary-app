import streamlit as st
import datetime
import math
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import calendar

# --- 1. ページ設定 ---
st.set_page_config(page_title="給料帳", layout="centered")

# --- 2. デザイン ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    .block-container { padding-top: 2rem; padding-bottom: 5rem; max-width: 600px; }
    
    .calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; margin-top: 5px; }
    .cal-header { text-align: center; font-size: 10px; font-weight: bold; color: #aaa; padding-bottom: 2px; }
    .cal-day { background-color: #262730; border: 1px solid #333; border-radius: 4px; height: 50px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
    .cal-num { font-size: 10px; color: #ccc; margin: 0; line-height: 1.2; }
    .cal-pay { font-size: 8.5px; font-weight: bold; color: #4da6ff; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; padding: 0 2px; }
    .cal-today { border: 1px solid #4da6ff; background-color: #1e2a3a; }
    .cal-empty { background-color: transparent; border: none; }
    
    .total-area { text-align: center; padding: 10px; background-color: #262730; border-radius: 8px; border: 1px solid #444; color: #fff; margin-bottom: 15px; }
    .total-amount { font-size: 22px; font-weight: bold; color: #4da6ff; }
    .total-sub { font-size: 10px; color: #aaa; }
    
    .history-row { padding: 6px 0; display: flex; justify-content: space-between; align-items: center; color: #eee; border-bottom: 1px solid #333; }
    .tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-right: 5px; font-weight: normal; display: inline-block; }
    .tag-work { background: #1c3a5e; color: #aaddff; }
    .tag-break { background: #4a1a1a; color: #ffaaaa; }
    .tag-drive { background: #1a4a3a; color: #aaffdd; }
    .tag-direct { background: #5e4a1c; color: #ffddaa; border: 1px solid #cc9900; }
    .tag-other { background: #444444; color: #dddddd; border: 1px solid #666; }
    .tag-plus { color: #aaffdd; font-weight: bold; }
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
        df = conn.read(worksheet="settings", ttl=600)
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

# --- 4. 計算ロジック (タイムライン方式) ---
NIGHT_START = 22 * 60       # 22:00 (1320)
NIGHT_END = 27 * 60         # 27:00 (1620)
OVERTIME_THRESHOLD = 8 * 60 # 480分

def calculate_driving_allowance(km):
    km = int(km)
    if km == 0: return 0
    if km < 10: return 150
    if km >= 340: return 3300
    return 300 + (math.floor((km - 10) / 30) * 300)

def calculate_direct_drive_pay(km):
    return int(km) * 25

def calculate_daily_total(records, base_wage, drive_wage):
    # 1. タイムライン初期化 (0:00 ~ 48:00まで確保)
    # 配列のインデックス = 分
    timeline = [None] * (48 * 60)
    fixed_pay = 0
    
    # 2. 固定手当の計算 & アクティビティの振り分け
    work_drive_records = []
    break_records = []
    
    for r in records:
        if r['type'] == 'OTHER':
            fixed_pay += int(r['pay_amount'])
        elif r['type'] == 'DRIVE_DIRECT':
            # 直行直帰: 時間計算に含めない、距離手当のみ
            fixed_pay += calculate_direct_drive_pay(float(r['distance_km']))
        elif r['type'] == 'DRIVE':
            # 通常運転: 距離手当 + 時間計算対象
            fixed_pay += calculate_driving_allowance(float(r['distance_km']))
            work_drive_records.append(r)
        elif r['type'] == 'WORK':
            work_drive_records.append(r)
        elif r['type'] == 'BREAK':
            break_records.append(r)
            
    # 3. タイムラインへの塗り込み (上書きロジック)
    
    # Pass 1: 勤務・運転を塗る
    for r in work_drive_records:
        sh, sm = int(r['start_h']), int(r['start_m'])
        eh, em = int(r['end_h']), int(r['end_m'])
        start_m = sh * 60 + sm
        end_m = eh * 60 + em
        
        activity = 'DRIVE' if r['type'] == 'DRIVE' else 'WORK'
        
        for m in range(start_m, end_m):
            if m < len(timeline):
                timeline[m] = activity
                
    # Pass 2: 休憩を上書きする (これにより重複部分が休憩になる)
    for r in break_records:
        sh, sm = int(r['start_h']), int(r['start_m'])
        eh, em = int(r['end_h']), int(r['end_m'])
        start_m = sh * 60 + sm
        end_m = eh * 60 + em
        
        for m in range(start_m, end_m):
            if m < len(timeline):
                timeline[m] = 'BREAK'
                
    # 4. 積み上げ計算
    total_work_pay = 0.0
    accumulated_work_minutes = 0
    
    min_wage_work = base_wage / 60
    min_wage_drive = drive_wage / 60
    
    for m in range(len(timeline)):
        act = timeline[m]
        
        # WORKまたはDRIVEの場合のみ計算 (BREAKやNoneはスキップ)
        if act in ['WORK', 'DRIVE']:
            # 基本単価
            rate = min_wage_drive if act == 'DRIVE' else min_wage_work
            
            # 割増判定
            is_night = (NIGHT_START <= m < NIGHT_END)
            is_overtime = (accumulated_work_minutes >= OVERTIME_THRESHOLD)
            
            multiplier = 1.0
            if is_night and is_overtime:
                multiplier = 1.5625 # 1.25 * 1.25
            elif is_night or is_overtime:
                multiplier = 1.25
                
            total_work_pay += rate * multiplier
            accumulated_work_minutes += 1
            
    return math.floor(total_work_pay) + fixed_pay, accumulated_work_minutes

def format_time_label(h, m):
    prefix = "翌" if h >= 24 else ""
    disp_h = h - 24 if h >= 24 else h
    return f"{prefix}{disp_h:02}:{m:02}"

# --- 5. セッション ---
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

# --- 6. メイン表示 ---
tab_input, tab_calendar, tab_setting = st.tabs(["日次入力", "カレンダー", "設定"])

# ==========================================
# TAB: 設定
# ==========================================
with tab_setting:
    st.write("")
    st.subheader("設定")
    c1, c2 = st.columns(2)
    new_wage = c1.number_input("基本時給 (円)", value=st.session_state.base_wage, step=10)
    new_drive_wage = c2.number_input("運転時給 (円)", value=st.session_state.wage_drive, step=10)
    
    if st.button("保存"):
        st.session_state.base_wage = new_wage
        st.session_state.wage_drive = new_drive_wage
        save_setting('base_wage', new_wage)
        save_setting('wage_drive', new_drive_wage)
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
    
    def time_sliders(label, kh, km, dh, dm):
        curr_h = st.session_state.get(kh, dh)
        curr_m = st.session_state.get(km, dm)
        st.markdown(f"<div style='font-size:11px; font-weight:bold; color:#aaa;'>{label}: <span style='color:#4da6ff;'>{format_time_label(curr_h, curr_m)}</span></div>", unsafe_allow_html=True)
        c1, c2 = st.columns([1.3, 1])
        with c1: vh = st.slider("時", 0, 33, dh, key=kh, label_visibility="collapsed")
        with c2: vm = st.slider("分", 0, 59, dm, key=km, step=1, label_visibility="collapsed")
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
        sh, sm = time_sliders("開始", "sh_in", "sm_in", 9, 0)
        eh, em = time_sliders("終了", "eh_in", "em_in", 18, 0)
        
        dist_km = 0
        is_direct = False
        
        if "運転" in record_type:
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
            is_direct = st.toggle("直行直帰 (時給なし・25円/km)", value=False)
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
            if (sh*60+sm) >= (eh*60+em):
                st.error("開始 < 終了 にしてください")
            else:
                if "運転" in record_type:
                    r_code = "DRIVE_DIRECT" if is_direct
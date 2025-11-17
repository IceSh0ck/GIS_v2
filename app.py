import os
import folium
import pandas as pd
import geopandas as gpd
from flask import Flask, render_template, request, redirect, url_for
from supabase import create_client, Client

app = Flask(__name__)

# --- Supabase Bağlantısı ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Supabase bağlantısı başarılı.")
except Exception as e:
    print(f"HATA: Supabase anahtarları eksik veya geçersiz. Lütfen OnRender Environment'ı kontrol edin. Hata: {e}")
    supabase = None
# ---------------------------

# --- Ağırlıklar ---
AGIRLIK_SICAKLIK = 0.50
AGIRLIK_NEM = 0.35
AGIRLIK_EGIM = 0.15

# --- Puanlama Fonksiyonları (1-5 arası) ---
def puanla_sicaklik(deger): # 'deger' radyasyon
    if deger > 2000: return 5
    if deger > 1800: return 4
    if deger > 1600: return 3
    if deger > 1400: return 2
    return 1

def puanla_nem(deger): # 'deger' yüzde
    if deger < 30: return 5  # Düşük nem GES için iyidir
    if deger < 40: return 4
    if deger < 50: return 3
    if deger < 60: return 2
    return 1

def puanla_egim(deger): # 'deger' derece/yüzde
    if deger >= 0 and deger <= 5: return 5 # İdeal eğim
    if deger > 5 and deger <= 10: return 4
    if deger > 10 and deger <= 15: return 3
    if deger > 15 and egim <= 20: return 2
    return 1

PUANLAMA_FONKSIYONLARI = {
    'sicaklik': puanla_sicaklik,
    'nem': puanla_nem,
    'egim': puanla_egim
}
PUAN_SUTUNLARI = {
    'sicaklik': 'puan_sicaklik',
    'nem': 'puan_nem',
    'egim': 'puan_egim'
}

def get_color(puan):
    if puan is None or puan == 0: return 'gray' # Veri yoksa gri
    if puan > 4.5: return 'darkgreen'
    if puan > 3.5: return 'green'
    if puan > 2.5: return 'orange'
    if puan > 1.5: return 'lightred'
    return 'darkred'

ILCE_LISTESI = [
    "Akyurt","Altındağ","Ayaş","Bala","Beypazarı","Çamlıdere","Çankaya",
    "Çubuk","Elmadağ","Etimesgut","Evren","Gölbaşı","Güdül","Haymana",
    "Kalecik","Kazan","Keçiören","Kızılcahamam","Mamak","Nallıhan",
    "Polatlı","Pursaklar","Şereflikoçhisar","Sincan","Yenimahalle"
]

# --- Ankara İlçe Verisini SADECE 1 KEZ YÜKLE ---
# ** DÜZELTME: Hatalı optimizasyonu (folium.GeoJson) kaldırdık **
# Sadece Geopandas DataFrame'ini (gdf) hafızaya alıyoruz.
try:
    geojson_path = os.path.join(app.static_folder, 'ankara_ilceler.geojson')
    ankara_ilceler_gdf = gpd.read_file(geojson_path)
    ankara_ilceler_gdf = ankara_ilceler_gdf.set_crs("EPSG:4326")
    print("Ankara ilçe sınırları (GDF) hafızaya yüklendi.")
    
except Exception as e:
    print(f"UYARI: 'static/ankara_ilceler.geojson' dosyası okunamadı. Hata: {e}")
    ankara_ilceler_gdf = None # Hatalı optimizasyon kaldırıldı
# ------------------------------------

def create_base_map():
    m = folium.Map(location=[39.93, 32.85], zoom_start=9)
    # ** DÜZELTME: "Yavaş" ama çalışan koda geri döndük **
    # Her harita için hafızadaki GDF'ten YENİ bir katman oluşturuyoruz.
    # Bu, HTML'in büyük olmasına neden olur, ancak sınırların görünmesini sağlar.
    if ankara_ilceler_gdf is not None:
        folium.GeoJson(
            ankara_ilceler_gdf,
            name='İlçe Sınırları',
            style_function=lambda x: {'fillColor': 'transparent', 'color': 'black', 'weight': 1, 'fillOpacity': 0.1}
        ).add_to(m)
    return m
# ------------------------------------

@app.route('/', methods=['GET', 'POST', 'HEAD'])
def index():
    
    # UptimeRobot ve Render sağlık kontrolleri (HEAD) için anında yanıt ver.
    if request.method == 'HEAD':
        return "", 200 # Boş bir 'OK' yanıtı

    # --- VERİ YÜKLEME (POST) ---
    if request.method == 'POST':
        if not supabase: 
             return redirect(url_for('index'))
            
        try:
            data_type = request.form.get('data_type') 
            ilce = request.form.get('ilce')
            file = request.files.get('csv_file')
            
            if not file or not data_type:
                raise ValueError("Eksik form verisi: Veri Tipi veya CSV dosyası seçilmedi.")

            df = pd.read_csv(file)
            if not all(col in df.columns for col in ['lat', 'lon', 'deger']):
                raise ValueError("CSV dosyasında 'lat', 'lon', 'deger' sütunları bulunmalı.")

            puan_func = PUANLAMA_FONKSIYONLARI[data_type]
            puan_column_name = PUAN_SUTUNLARI[data_type]
            
            data_to_upsert = []
            for _, row in df.iterrows():
                puan = puan_func(row['deger'])
                record = {
                    'lat': row['lat'],
                    'lon': row['lon'],
                    'ilce': ilce,
                    puan_column_name: puan
                }
                data_to_upsert.append(record)

            supabase.table('ges_noktalar').upsert(
                data_to_upsert, 
                on_conflict='lat,lon'
            ).execute()
            
            print(f"{len(data_to_upsert)} adet '{data_type}' verisi başarıyla yüklendi/güncellendi.")

        except Exception as e:
            print(f"HATA: Veri yüklenemedi. Hata: {e}")
            return redirect(url_for('index', error=str(e)))
        
        return redirect(url_for('index'))

    # --- HARİTA GÖSTERİMİ (GET) ---
    map_htmls = {}
    
    try:
        m_base = create_base_map()
        m_sicaklik = create_base_map()
        m_nem = create_base_map()
        m_egim = create_base_map()
        m_toplu = create_base_map()
        
        df_data = pd.DataFrame() 
        if supabase:
            response = supabase.table('ges_noktalar').select("*").execute()
            if response.data:
                df_data = pd.DataFrame(response.data)
                
        if not df_data.empty:
            if 'puan_sicaklik' not in df_data.columns: df_data['puan_sicaklik'] = 0
            if 'puan_nem' not in df_data.columns: df_data['puan_nem'] = 0
            if 'puan_egim' not in df_data.columns: df_data['puan_egim'] = 0
            
            df_data.fillna(0, inplace=True)

            df_data['Genel_Skor'] = (df_data['puan_sicaklik'] * AGIRLIK_SICAKLIK) + \
                                    (df_data['puan_nem'] * AGIRLIK_NEM) + \
                                    (df_data['puan_egim'] * AGIRLIK_EGIM)

            for _, row in df_data.iterrows():
                tooltip_sicaklik = f"Sıcaklık Puanı: {row['puan_sicaklik']}"
                tooltip_nem = f"Nem Puanı: {row['puan_nem']}"
                tooltip_egim = f"Eğim Puanı: {row['puan_egim']}"
                tooltip_toplu = f"Genel Skor: {row['Genel_Skor']:.2f}<br>Sıc P: {row['puan_sicaklik']}<br>Nem P: {row['puan_nem']}<br>Eğim P: {row['puan_egim']}"

                folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color=get_color(row['puan_sicaklik']), fill=True, fill_opacity=0.8, tooltip=tooltip_sicaklik).add_to(m_sicaklik)
                folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color=get_color(row['puan_nem']), fill=True, fill_opacity=0.8, tooltip=tooltip_nem).add_to(m_nem)
                folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color=get_color(row['puan_egim']), fill=True, fill_opacity=0.8, tooltip=tooltip_egim).add_to(m_egim)
                folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color=get_color(row['Genel_Skor']), fill=True, fill_opacity=0.8, tooltip=tooltip_toplu).add_to(m_toplu)
        else:
            print("Veritabanında veri yok. Sadece boş haritalar oluşturuldu.")

        map_htmls['base'] = m_base._repr_html_()
        map_htmls['sicaklik'] = m_sicaklik._repr_html_()
        map_htmls['nem'] = m_nem._repr_html_()
        map_htmls['egim'] = m_egim._repr_html_()
        map_htmls['toplu'] = m_toplu._repr_html_()

    except Exception as e:
        print(f"HATA: Haritalar oluşturulamadı. Hata: {e}")
        if 'base' not in map_htmls:
             m_base = create_base_map()
             map_htmls['base'] = m_base._repr_html_()
        return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls, error=str(e))
        
    return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

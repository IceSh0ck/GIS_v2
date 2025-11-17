import os
import folium
import pandas as pd
import geopandas as gpd
from flask import Flask, render_template, request

app = Flask(__name__)

# --- Ağırlıklar ---
AGIRLIK_SICAKLIK = 0.50
AGIRLIK_NEM = 0.35
AGIRLIK_EGIM = 0.15

# --- Puanlama Fonksiyonları (1-5 arası) ---
def puanla_sicaklik(radyasyon):
    if radyasyon > 2000: return 5
    if radyasyon > 1800: return 4
    if radyasyon > 1600: return 3
    if radyasyon > 1400: return 2
    return 1

def puanla_nem(nem):
    if nem < 30: return 5  # Düşük nem GES için iyidir
    if nem < 40: return 4
    if nem < 50: return 3
    if nem < 60: return 2
    return 1

def puanla_egim(egim):
    if egim >= 0 and egim <= 5: return 5 # İdeal eğim
    if egim > 5 and egim <= 10: return 4
    if egim > 10 and egim <= 15: return 3
    if egim > 15 and egim <= 20: return 2
    return 1

# Puanlara göre renk döndüren yardımcı fonksiyon
def get_color(puan):
    if puan > 4.5: return 'darkgreen'
    if puan > 3.5: return 'green'
    if puan > 2.5: return 'orange'
    if puan > 1.5: return 'lightred'
    return 'darkred'

# --- YENİ GÜNCEL İLÇE LİSTESİ ---
ILCE_LISTESI = [
    "Akyurt","Altındağ","Ayaş","Bala","Beypazarı","Çamlıdere","Çankaya",
    "Çubuk","Elmadağ","Etimesgut","Evren","Gölbaşı","Güdül","Haymana",
    "Kalecik","Kazan","Keçiören","Kızılcahamam","Mamak","Nallıhan",
    "Polatlı","Pursaklar","Şereflikoçhisar","Sincan","Yenimahalle"
]
# ------------------------------------

# --- Ankara İlçe Verisini Yükle (Sadece Harita Çizimi İçin) ---
try:
    geojson_path = os.path.join(app.static_folder, 'ankara_ilceler.geojson')
    ankara_ilceler_gdf = gpd.read_file(geojson_path)
    ankara_ilceler_gdf = ankara_ilceler_gdf.set_crs("EPSG:4326")
except Exception as e:
    print(f"UYARI: 'static/ankara_ilceler.geojson' dosyası okunamadı. Hata: {e}")
    ankara_ilceler_gdf = None
# ------------------------------------

# --- HARİTA OLUŞTURMA FONKSİYONU ---
# Her haritayı sıfırdan ve temiz oluşturmak için yardımcı fonksiyon
def create_base_map():
    m = folium.Map(location=[39.93, 32.85], zoom_start=9)
    if ankara_ilceler_gdf is not None:
        folium.GeoJson(
            ankara_ilceler_gdf,
            name='İlçe Sınırları',
            style_function=lambda x: {'fillColor': 'transparent', 'color': 'black', 'weight': 1, 'fillOpacity': 0.1}
        ).add_to(m)
    return m
# ------------------------------------

@app.route('/', methods=['GET', 'POST'])
def index():
    
    map_htmls = {}
    
    # 1. Ana Haritayı (Base) her durumda oluştur
    m_base = create_base_map()
    map_htmls['base'] = m_base._repr_html_()

    if request.method == 'GET':
        # Sayfa ilk açıldığında sadece ana haritayı göster
        return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls)

    if request.method == 'POST':
        # 2. Formdan verileri al
        file = request.files.get('csv_file')
        ilce = request.form.get('ilce')

        if not file:
            # CSV dosyası yüklenmediyse hata verme, sadece ana haritayı göster
            return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls)
        
        try:
            # 3. CSV'yi Pandas DataFrame'e oku
            df = pd.read_csv(file)
            if not all(col in df.columns for col in ['lat', 'lon', 'sicaklik_radyasyon', 'nem', 'egim']):
                raise ValueError("CSV dosyasında 'lat', 'lon', 'sicaklik_radyasyon', 'nem', 'egim' sütunları bulunmalı.")

            # 4. Puanlamayı yap
            df['Puan_Sicaklik'] = df['sicaklik_radyasyon'].apply(puanla_sicaklik)
            df['Puan_Nem'] = df['nem'].apply(puanla_nem)
            df['Puan_Egim'] = df['egim'].apply(puanla_egim)
            df['Genel_Skor'] = (df['Puan_Sicaklik'] * AGIRLIK_SICAKLIK) + \
                                 (df['Puan_Nem'] * AGIRLIK_NEM) + \
                                 (df['Puan_Egim'] * AGIRLIK_EGIM)

            # 5. DÖRT YENİ HARİTAYI BAĞIMSIZCA OLUŞTUR
            m_sicaklik = create_base_map()
            m_nem = create_base_map()
            m_egim = create_base_map()
            m_toplu = create_base_map()

            # 6. Noktaları ilgili haritalara ekle
            for _, row in df.iterrows():
                tooltip_sicaklik = f"Sıcaklık: {row['sicaklik_radyasyon']} (Puan: {row['Puan_Sicaklik']})"
                tooltip_nem = f"Nem: {row['nem']} (Puan: {row['Puan_Nem']})"
                tooltip_egim = f"Eğim: {row['egim']} (Puan: {row['Puan_Egim']})"
                tooltip_toplu = f"Genel Skor: {row['Genel_Skor']:.2f}<br>Sıcaklık P: {row['Puan_Sicaklik']}<br>Nem P: {row['Puan_Nem']}<br>Eğim P: {row['Puan_Egim']}"

                folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color=get_color(row['Puan_Sicaklik']), fill=True, fill_opacity=0.8, tooltip=tooltip_sicaklik).add_to(m_sicaklik)
                folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color=get_color(row['Puan_Nem']), fill=True, fill_opacity=0.8, tooltip=tooltip_nem).add_to(m_nem)
                folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color=get_color(row['Puan_Egim']), fill=True, fill_opacity=0.8, tooltip=tooltip_egim).add_to(m_egim)
                folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color=get_color(row['Genel_Skor']), fill=True, fill_opacity=0.8, tooltip=tooltip_toplu).add_to(m_toplu)

            # 7. Tüm haritaları HTML'e çevir (Base map zaten eklenmişti)
            map_htmls['sicaklik'] = m_sicaklik._repr_html_()
            map_htmls['nem'] = m_nem._repr_html_()
            map_htmls['egim'] = m_egim._repr_html_()
            map_htmls['toplu'] = m_toplu._repr_html_()

            return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls)

        except Exception as e:
            print(f"HATA: CSV işlenemedi veya harita oluşturulamadı. Hata: {e}")
            # Hata durumunda sadece temel haritayı göster
            return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls, error=str(e))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

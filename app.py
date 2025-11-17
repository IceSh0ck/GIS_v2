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
# Bunları kendi kriterlerinize göre detaylandırabilirsiniz.
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
# İlçe listesini artık doğrudan buraya yazıyoruz.
ILCE_LISTESI = [
    "Akyurt","Altındağ","Ayaş","Bala","Beypazarı","Çamlıdere","Çankaya",
    "Çubuk","Elmadağ","Etimesgut","Evren","Gölbaşı","Güdül","Haymana",
    "Kalecik","Kazan","Keçiören","Kızılcahamam","Mamak","Nallıhan",
    "Polatlı","Pursaklar","Şereflikoçhisar","Sincan","Yenimahalle"
]
# ------------------------------------

# --- Ankara İlçe Verisini Yükle (Sadece Harita Çizimi İçin) ---
# static/ankara_ilceler.geojson dosyasını okur
try:
    geojson_path = os.path.join(app.static_folder, 'ankara_ilceler.geojson')
    ankara_ilceler_gdf = gpd.read_file(geojson_path)
    
    # --- HATA ÇÖZÜMÜ (CRS TANIMLAMA) ---
    # Gelen TopoJSON dosyasında CRS (Koordinat Referans Sistemi) bilgisi eksik.
    # Folium'un haritayı çizebilmesi için verinin CRS'ini manuel olarak EPSG:4326 (standart enlem/boylam) olarak tanımlıyoruz.
    ankara_ilceler_gdf = ankara_ilceler_gdf.set_crs("EPSG:4326")
    # ------------------------------------

except Exception as e:
    print(f"UYARI: 'static/ankara_ilceler.geojson' dosyası okunamadı veya bulunamadı. Haritada ilçe sınırları GÖRÜNMEYECEK. Hata: {e}")
    ankara_ilceler_gdf = None # Kodun çökmesini engelle, None olarak devam et

# --- Ana Rota (Kontrol Paneli ve Haritalar) ---
@app.route('/', methods=['GET', 'POST'])
def index():
    
    # Haritaları tutacak sözlük
    map_htmls = {}

    # Temel Ankara Haritasını Oluştur
    m_base = folium.Map(location=[39.93, 32.85], zoom_start=9)
    
    # Eğer GeoJSON başarıyla yüklendiyse sınırları haritaya ekle
    if ankara_ilceler_gdf is not None:
        folium.GeoJson(
            ankara_ilceler_gdf,
            name='İlçe Sınırları',
            style_function=lambda x: {'fillColor': 'transparent', 'color': 'black', 'weight': 1}
        ).add_to(m_base)

    if request.method == 'POST':
        # 1. Formdan verileri al
        file = request.files['csv_file']
        ilce = request.form['ilce'] # Seçilen ilçe (Şimdilik sadece bilgi amaçlı)

        if file:
            try:
                # 2. CSV'yi Pandas DataFrame'e oku
                # Sütun isimleri: lat,lon,sicaklik_radyasyon,nem,egim olmalı
                df = pd.read_csv(file)

                # 3. Puanlamayı yap
                df['Puan_Sicaklik'] = df['sicaklik_radyasyon'].apply(puanla_sicaklik)
                df['Puan_Nem'] = df['nem'].apply(puanla_nem)
                df['Puan_Egim'] = df['egim'].apply(puanla_egim)

                # 4. Ağırlıklı Toplam Skoru Hesapla
                df['Genel_Skor'] = (df['Puan_Sicaklik'] * AGIRLIK_SICAKLIK) + \
                                     (df['Puan_Nem'] * AGIRLIK_NEM) + \
                                     (df['Puan_Egim'] * AGIRLIK_EGIM)

                # 5. Haritaları oluştur
                # Kopyalarını oluşturarak 4 ayrı harita yapıyoruz
                m_sicaklik = m_base
                m_nem = folium.Map(location=[39.93, 32.85], zoom_start=9)
                m_egim = folium.Map(location=[39.93, 32.85], zoom_start=9)
                m_toplu = folium.Map(location=[39.93, 32.85], zoom_start=9)
                
                # İlçe sınırlarını diğer haritalara da ekle
                if ankara_ilceler_gdf is not None:
                    folium.GeoJson(ankara_ilceler_gdf, style_function=lambda x: {'fillColor': 'transparent', 'color': 'black', 'weight': 1}).add_to(m_nem)
                    folium.GeoJson(ankara_ilceler_gdf, style_function=lambda x: {'fillColor': 'transparent', 'color': 'black', 'weight': 1}).add_to(m_egim)
                    folium.GeoJson(ankara_ilceler_gdf, style_function=lambda x: {'fillColor': 'transparent', 'color': 'black', 'weight': 1}).add_to(m_toplu)


                # Her bir noktayı haritalara puanına göre işle
                for _, row in df.iterrows():
                    # Tooltip (üzerine gelince görünecek bilgi)
                    tooltip_sicaklik = f"Sıcaklık: {row['sicaklik_radyasyon']} (Puan: {row['Puan_Sicaklik']})"
                    tooltip_nem = f"Nem: {row['nem']} (Puan: {row['Puan_Nem']})"
                    tooltip_egim = f"Eğim: {row['egim']} (Puan: {row['Puan_Egim']})"
                    tooltip_toplu = f"Genel Skor: {row['Genel_Skor']:.2f}<br>Sıcaklık P: {row['Puan_Sicaklik']}<br>Nem P: {row['Puan_Nem']}<br>Eğim P: {row['Puan_Egim']}"

                    # Noktaları haritalara ekle
                    folium.CircleMarker(
                        location=[row['lat'], row['lon']], radius=5,
                        color=get_color(row['Puan_Sicaklik']), fill=True, fill_opacity=0.8,
                        tooltip=tooltip_sicaklik
                    ).add_to(m_sicaklik)
                    
                    folium.CircleMarker(
                        location=[row['lat'], row['lon']], radius=5,
                        color=get_color(row['Puan_Nem']), fill=True, fill_opacity=0.8,
                        tooltip=tooltip_nem
                    ).add_to(m_nem)

                    folium.CircleMarker(
                        location=[row['lat'], row['lon']], radius=5,
                        color=get_color(row['Puan_Egim']), fill=True, fill_opacity=0.8,
                        tooltip=tooltip_egim
                    ).add_to(m_egim)

                    folium.CircleMarker(
                        location=[row['lat'], row['lon']], radius=5,
                        color=get_color(row['Genel_Skor']), fill=True, fill_opacity=0.8,
                        tooltip=tooltip_toplu
                    ).add_to(m_toplu)

                # 6. Haritaları HTML'e çevir
                map_htmls['sicaklik'] = m_sicaklik._repr_html_()
                map_htmls['nem'] = m_nem._repr_html_()
                map_htmls['egim'] = m_egim._repr_html_()
                map_htmls['toplu'] = m_toplu._repr_html_()

                return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls)

            except Exception as e:
                print(f"HATA: CSV işlenemedi. Hata: {e}")
                # Hata durumunda sadece temel haritayı göster
                map_htmls['base'] = m_base._repr_html_()
                return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls)

    # GET request (sayfa ilk açıldığında)
    map_htmls['base'] = m_base._repr_html_()
    return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls)

if __name__ == '__main__':
    # OnRender'ın port değişkenini kullanması için
    port = int(os.environ.get('PORT', 5000))
    # host='0.0.0.0' ayarı OnRender için kritiktir.
    app.run(host='0.0.0.0', port=port, debug=True)

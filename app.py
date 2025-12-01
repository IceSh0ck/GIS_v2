import os
import folium
import pandas as pd
import geopandas as gpd
from flask import Flask, render_template, request, redirect, url_for, jsonify
from supabase import create_client, Client

app = Flask(__name__)

# --- 1. SUPABASE BAĞLANTISI ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Supabase bağlantısı başarılı.")
except Exception as e:
    print(f"HATA: Supabase anahtarları eksik veya geçersiz. Hata: {e}")
    supabase = None

# --- 2. ANALİZ AYARLARI (AĞIRLIKLAR) ---
AGIRLIK_SICAKLIK = 0.50
AGIRLIK_NEM = 0.35
AGIRLIK_EGIM = 0.15

# --- 3. PUANLAMA FONKSİYONLARI ---
def puanla_sicaklik(deger): # Radyasyon
    try: deger = float(deger)
    except: return 1
    if deger > 2000: return 5
    if deger > 1800: return 4
    if deger > 1600: return 3
    if deger > 1400: return 2
    return 1

def puanla_nem(deger): # Yüzde Nem
    try: deger = float(deger)
    except: return 1
    if deger < 30: return 5  # Düşük nem GES için iyidir
    if deger < 40: return 4
    if deger < 50: return 3
    if deger < 60: return 2
    return 1

def puanla_egim(deger): # Derece Eğim
    try: deger = float(deger)
    except: return 1
    if deger >= 0 and deger <= 5: return 5 # İdeal eğim
    if deger > 5 and deger <= 10: return 4
    if deger > 10 and deger <= 15: return 3
    if deger > 15 and deger <= 20: return 2
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
    if puan is None or puan == 0: return 'gray'
    if puan > 4.5: return 'darkgreen'
    if puan > 3.5: return 'green'
    if puan > 2.5: return 'orange'
    if puan > 1.5: return 'lightred'
    return 'darkred'

ILCE_LISTESI = [
    "Akyurt","Altındağ","Ayaş","Bala","Beypazarı","Çamlıdere","Çankaya",
    "Çubuk","Elmadağ","Etimesgut","Evren","Gölbaşı","Güdül","Haymana",
    "Kalecik","Kahramankazan","Keçiören","Kızılcahamam","Mamak","Nallıhan",
    "Polatlı","Pursaklar","Şereflikoçhisar","Sincan","Yenimahalle"
]

# --- 4. GEOJSON VERİSİNİ YÜKLEME ---
# Bu veri hem ana harita çizimi hem de "İlçe Sınırlarını Getirme" API'si için gerekli.
ankara_ilceler_gdf = None
try:
    geojson_path = os.path.join(app.static_folder, 'ankara_ilceler.geojson')
    ankara_ilceler_gdf = gpd.read_file(geojson_path)
    # Koordinat sistemini garantiye alalım
    if ankara_ilceler_gdf.crs is None:
        ankara_ilceler_gdf = ankara_ilceler_gdf.set_crs("EPSG:4326")
    else:
        ankara_ilceler_gdf = ankara_ilceler_gdf.to_crs("EPSG:4326")
        
    print("Ankara ilçe sınırları (GDF) hafızaya yüklendi.")
    
except Exception as e:
    print(f"UYARI: 'static/ankara_ilceler.geojson' dosyası okunamadı veya hatalı. Hata: {e}")

# --- 5. YARDIMCI FONKSİYONLAR ---
def create_base_map():
    m = folium.Map(location=[39.93, 32.85], zoom_start=9)
    # Arka planda silik ilçe sınırlarını göster (Genel görünüm için)
    if ankara_ilceler_gdf is not None:
        folium.GeoJson(
            ankara_ilceler_gdf,
            name='İlçe Sınırları',
            style_function=lambda x: {'fillColor': 'transparent', 'color': 'gray', 'weight': 1, 'fillOpacity': 0.05}
        ).add_to(m)
    return m

# ==========================================
#                  ROUTELAR
# ==========================================

@app.route('/', methods=['GET', 'POST', 'HEAD'])
def index():
    # Uptime kontrolü için
    if request.method == 'HEAD':
        return "", 200

    # --- A) CSV VERİ YÜKLEME (POST) ---
    if request.method == 'POST':
        if not supabase: 
             return redirect(url_for('index'))
            
        try:
            data_type = request.form.get('data_type') 
            ilce = request.form.get('ilce')
            file = request.files.get('csv_file')
            
            if not file or not data_type:
                raise ValueError("Eksik form verisi.")

            df = pd.read_csv(file)
            # Kolon kontrolü
            if not all(col in df.columns for col in ['lat', 'lon', 'deger']):
                raise ValueError("CSV formatı hatalı. 'lat', 'lon', 'deger' sütunları gerekli.")

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

            # Supabase Upsert (lat,lon çakışırsa güncelle)
            supabase.table('ges_noktalar').upsert(data_to_upsert, on_conflict='lat,lon').execute()
            print(f"CSV: {len(data_to_upsert)} adet veri yüklendi.")

        except Exception as e:
            print(f"HATA: {e}")
            return redirect(url_for('index', error=str(e)))
        
        return redirect(url_for('index'))

    # --- B) HARİTA GÖSTERİMİ (GET) ---
    map_htmls = {}
    
    try:
        # Boş haritaları oluştur
        m_base = create_base_map()
        m_sicaklik = create_base_map()
        m_nem = create_base_map()
        m_egim = create_base_map()
        m_toplu = create_base_map()
        
        # Verileri çek
        df_data = pd.DataFrame() 
        if supabase:
            response = supabase.table('ges_noktalar').select("*").execute()
            if response.data:
                df_data = pd.DataFrame(response.data)
                
        # Veri varsa haritaya işle
        if not df_data.empty:
            # Eksik kolonları tamamla (0 ile)
            for col in ['puan_sicaklik', 'puan_nem', 'puan_egim']:
                if col not in df_data.columns: df_data[col] = 0
            
            df_data.fillna(0, inplace=True)

            # Genel Skor Hesabı
            df_data['Genel_Skor'] = (df_data['puan_sicaklik'] * AGIRLIK_SICAKLIK) + \
                                    (df_data['puan_nem'] * AGIRLIK_NEM) + \
                                    (df_data['puan_egim'] * AGIRLIK_EGIM)

            # Noktaları haritalara ekle
            for _, row in df_data.iterrows():
                lat, lon = row['lat'], row['lon']
                
                # Tooltipler
                t_sicaklik = f"Sıcaklık Puanı: {row['puan_sicaklik']}"
                t_nem = f"Nem Puanı: {row['puan_nem']}"
                t_egim = f"Eğim Puanı: {row['puan_egim']}"
                t_toplu = f"Genel Skor: {row['Genel_Skor']:.2f}"

                # Çemberleri ekle
                folium.CircleMarker([lat, lon], radius=5, color=get_color(row['puan_sicaklik']), fill=True, fill_opacity=0.8, tooltip=t_sicaklik).add_to(m_sicaklik)
                folium.CircleMarker([lat, lon], radius=5, color=get_color(row['puan_nem']), fill=True, fill_opacity=0.8, tooltip=t_nem).add_to(m_nem)
                folium.CircleMarker([lat, lon], radius=5, color=get_color(row['puan_egim']), fill=True, fill_opacity=0.8, tooltip=t_egim).add_to(m_egim)
                folium.CircleMarker([lat, lon], radius=5, color=get_color(row['Genel_Skor']), fill=True, fill_opacity=0.8, tooltip=t_toplu).add_to(m_toplu)

        # Haritaları HTML string'e çevir
        map_htmls['base'] = m_base._repr_html_()
        map_htmls['sicaklik'] = m_sicaklik._repr_html_()
        map_htmls['nem'] = m_nem._repr_html_()
        map_htmls['egim'] = m_egim._repr_html_()
        map_htmls['toplu'] = m_toplu._repr_html_()

    except Exception as e:
        print(f"Harita Oluşturma Hatası: {e}")
        # Hata durumunda en azından boş base harita dönsün
        m_base = create_base_map()
        map_htmls['base'] = m_base._repr_html_()
        return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls, error=str(e))
        
    return render_template('index.html', ilceler=ILCE_LISTESI, maps=map_htmls)

# --- C) YENİ: MANUEL VERİ KAYDETME (JSON API) ---
@app.route('/save_manual_data', methods=['POST'])
def save_manual_data():
    if not supabase:
        return jsonify({'success': False, 'error': 'Veritabanı bağlantısı yok'})

    try:
        req_data = request.get_json()
        ilce = req_data.get('ilce')
        data_type = req_data.get('data_type')
        points = req_data.get('points', [])

        if not points:
            return jsonify({'success': False, 'error': 'Kaydedilecek veri noktası bulunamadı.'})

        puan_func = PUANLAMA_FONKSIYONLARI[data_type]
        puan_column_name = PUAN_SUTUNLARI[data_type]

        data_to_upsert = []
        for point in points:
            puan = puan_func(point['deger'])
            record = {
                'lat': point['lat'],
                'lon': point['lon'],
                'ilce': ilce,
                puan_column_name: puan
            }
            data_to_upsert.append(record)

        # Veritabanına kaydet
        supabase.table('ges_noktalar').upsert(data_to_upsert, on_conflict='lat,lon').execute()
        
        return jsonify({'success': True, 'message': f'{len(data_to_upsert)} nokta başarıyla kaydedildi!'})

    except Exception as e:
        print(f"Manuel Kayıt Hatası: {e}")
        return jsonify({'success': False, 'error': str(e)})

# --- D) YENİ: İLÇE SINIRINI GETİREN ENDPOINT (Zoom ve Vurgulama İçin) ---
@app.route('/get_district_boundary/<ilce_ad>', methods=['GET'])
def get_district_boundary(ilce_ad):
    if ankara_ilceler_gdf is None:
        return jsonify({'success': False, 'error': 'GeoJSON dosyası sunucuda yüklü değil.'})
    
    try:
        # GeoJSON dosyasındaki "name" kolonunda ilçe adını arıyoruz.
        # Senin gönderdiğin veride ilçe isimleri "name" property'si altındaydı.
        district = ankara_ilceler_gdf[ankara_ilceler_gdf['name'] == ilce_ad]
        
        if district.empty:
            # Bazen Türkçe karakter sorunu olabilir (Kazan -> Kahramankazan vb.)
            # Basit bir deneme daha yapalım:
            return jsonify({'success': False, 'error': 'İlçe bulunamadı'})
            
        # Bulunan ilçeyi GeoJSON string olarak döndür
        return district.to_json()
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

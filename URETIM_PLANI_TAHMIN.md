# Üretim Planlama — Tahmin Modeli Dokümanı

> Bu doküman, Üretim Planlama sayfasındaki (ve Sunum Modu'ndaki) **Öngörülen Bitiş**
> tarihlerinin, **Zamanında Bitecek / Gecikecek** kararının ve **Finans** rozetinin
> nasıl hesaplandığını; sonuçları değiştirmek için kimin ne yapması gerektiğini anlatır.
> Son güncelleme: 23.07.2026

---

## 1. Temel Kavramlar

### İş günü
Bütün süre ve sapma hesapları **iş günü** cinsindendir:

| Gün | Değeri |
|---|---|
| Pazartesi–Cuma | 1 gün |
| Cumartesi–Pazar | 0 |
| Resmi tatil | 0 |
| Arife günü | 0,5 |

Tatil listesi sistemdeki **Resmi Tatil** tablosundan gelir; oraya eklenen her gün
tüm tahminleri otomatik etkiler.

### Gerçek Başlangıç (kanıta dayalı)
Bir görevin başlangıcı, sistemin görevi oluşturduğu an değil; **ilk somut iş
kanıtının** tarihi kabul edilir:

| Departman / Tür | Başlangıç kanıtı |
|---|---|
| Talaşlı imalat | İlk zaman kaydı (timer) |
| CNC kesim | İlk kesilen parça |
| Kaynaklı imalat | İlk kaynak saat girişi |
| Satın alma | İlk satın alma talebinin açılması |
| Dizayn | İlk teknik resim yayını |
| Diğerleri | Görevin "başladı" damgası |

### İlerleme (%)
Her görevin ilerlemesi zaten kullandığımız kaynaklardan gelir: CNC'de kesilen kg,
talaşlıda harcanan/tahmini saat, satın almada kalemlerin aşamaları, diğerlerinde
elle girilen yüzde. Ana görevler, alt görevlerinin ağırlıklı ortalamasıdır.

---

## 2. Görev Bazında "Öngörülen Bitiş" — Dört Kural

Her açık görevin tarihi şu dört kuraldan **biriyle** üretilir. Hangi kuralın
kullanıldığı, Plan Detayı penceresindeki **"Öngörü Dayanağı"** sütununda yazar.

### Kural 1 — Tempo (`"X günde %p · ~N g kaldı"`)
İlerlemesi %0'dan büyük, başlamış görevler için:

> Görev **E** iş gününde **%p** ilerlediyse, kalan işi aynı tempoyla
> **E × (100 − p) / p** iş gününde bitirir.

*Örnek (035-170, Panel B kaynak):* 16 iş gününde %70 → kalan %30 için
16 × 30/70 ≈ **7 iş günü** → bugünden 7 iş günü sonrası = Öngörülen Bitiş.

### Kural 2 — Ağırlık payı (`"ağırlık payı · ~N g"`)
Henüz **%0'da olan** ve **plan tarihi girilmemiş** görevler için (tempo yok):

> Önce işin kendi temposundan **toplam süre** tahmin edilir:
> iş, **E** iş gününde **%P** tamamlandıysa tamamı **E × 100 / P** sürer.
> Sonra görev, **ağırlık payı** kadarını alır:
> görev süresi = toplam süre × (görev ağırlığı ÷ kardeş ağırlıkları toplamı).
> Alt görevlerde pay, ana görevin payıyla çarpılır.

*Örnek (035-170, Boya):* İş 62 iş gününde %77 → toplam ≈ 80 gün.
Boya'nın payı: Üretim ana görevi %65 × Boya %5 ≈ %3 → **~2,5 iş günü**.

Önemli ayrıntı: **alt görevi olan ana görevler bu kuralı kullanmaz** — onların
gerçeği çocuklarında yaşar; kendi paylarını da sayarsak aynı iş iki kez sayılır.

### Kural 3 — İtme (`"İten: X"`)
Hiç başlamamış görevler, önce gelen görevin (açıkça bağlandığı görev, yoksa
sıradaki bir önceki ana görev) öngörülen bitişinin **ertesi iş gününe** atılır;
süresi Kural 2 veya 4'ten gelir. Bir görev gecikince arkasındakileri böyle "iter".

### Kural 4 — Plan penceresi
Hedef Başlangıç/Bitiş girilmiş görevler, planlanan pencere uzunluğunu kullanır.
Hiçbir bilgi yoksa 1 günlük yer tutucu kalır (`—` görünür).

**Üst sınır:** Hiçbir kalan-süre tahmini 260 iş gününü (≈ 1 yıl) aşamaz.

---

## 3. İş Emri Kararı (Zamanında / Gecikecek)

1. İş emrinin **Öngörülen Bitişi** = ağaçtaki (alt iş emirleri dâhil) **en geç**
   görev bitişi. İş, son görevi bittiğinde biter.
2. Bu tarih, iş emrinin **kendi Hedef Bitişi** ile karşılaştırılır (görevlerde
   tarih olmasa da bu alan Proje Takibi'nde her zaman vardır).
3. Fark iş günü cinsinden **Sapma**dır; artıysa **Gecikecek**, değilse
   **Zamanında Bitecek**.

Plan Detayı penceresinde bu tarihi belirleyen görev **🚩 "Bitişi belirleyen"**
olarak işaretlenir — "neden bu tarih?" sorusunun tek satırlık cevabı budur.

### Görev sınıflandırmaları

| Etiket | Anlamı | Gerekli veri |
|---|---|---|
| Plansız | Hedef tarih girilmemiş | — |
| Devam Ediyor / Başlamadı | Açık, hedefe göre sorunsuz | Hedef tarih |
| **Riskte** | Öngörü, görevin kendi hedefini aşıyor | Hedef tarih |
| **Gecikmede** | Hedef geçti, iş hâlâ açık | Hedef tarih |
| Geç Bitti / Zamanında | Kapanan işin sonucu | Hedef tarih |

> Görevlere hedef tarih girilmedikçe görev satırlarında sapma/uyarı **çıkamaz**;
> iş emri kararı yine üretilir ama görev bazlı erken uyarı kaybedilir.

---

## 4. Finans Rozeti (Sunum Modu)

Tutar göstermez; yalnız durum söyler. Kural:

> **Öngörülen maliyet** = max(Gerçekleşen, Tahmini Toplam − hayali kalemler)
> ile **satış fiyatı** karşılaştırılır.

"Hayali kalem": **teslim edilmiş** ama ne maliyet satırı girilmiş ne de gerçek
PO fiyatı olan kalemlerin tekliften gelen tahmini fiyatı (ör. stoktan verilen
malzeme). Teslim edilmiş bir kalemin alımı artık gerçekleşmeyeceği için bu fiyat
kurgudur ve yalnız **bu rozette** düşülür — **maliyet modülündeki tahminler
değişmez.**

| Rozet | Koşul |
|---|---|
| Kritik | Gerçekleşen ≥ fiyat, veya öngörülen maliyet > fiyat |
| Riskli | Öngörülen maliyet > fiyatın %90'ı, veya gerçekleşen > tahmini toplam |
| Sağlıklı | Yukarıdakilerin hiçbiri |
| Fiyat Yok / Veri Yok | Satış fiyatı ya da maliyet özeti yok |

---

## 5. Sonuçları Değiştirmek İçin Ne Yapmalı? (Kullanıcı)

| İstediğiniz | Yapılacak iş | Kim |
|---|---|---|
| Tahminler gerçeğe yaklaşsın | **İlerlemeleri güncel girin** (elle %, zaman kaydı, kesim tamamlama). %0 duran görev kaba tahmin alır. | İlgili departman |
| %0 görevlerin süresi mantıklı olsun | **Görev ağırlıklarını** gerçek efora göre ayarlayın — süre payı ağırlık payıdır. | Planlama |
| Görev bazlı Riskte/Gecikmede uyarısı | Görevlere **Hedef Başlangıç/Bitiş** girin (tamamlanmış görevlere geriye dönük de girilebilir). | Planlama |
| Doğru itme zinciri | Görevler arası **bağımlılıkları (depends_on)** tanımlayın; yoksa sıra numarası kullanılır. | Planlama |
| İş emri kararı doğru kıyaslansın | İş emrinin **Hedef Bitişini** güncel tutun (değişiklik sebebiyle kaydedilir, geçmişi Revizyonlar'da). | Proje sorumlusu |
| Finans rozeti gerçeği yansıtsın | Teslim alınan kalemlerin **maliyet satırlarını** girin; PO fiyatları kendiliğinden kullanılır. | Maliyet/Satın alma |
| Tatiller doğru sayılsın | **Resmi Tatil** tablosunu güncel tutun. | İK/Yönetim |

## 6. Ayar Noktaları (Geliştirici)

| Ayar | Yeri | Anlamı |
|---|---|---|
| `MAX_REMAINING_WD = 260` | `projects/services/schedule` sabitleri (`production_plan.py`) | Kalan süre üst sınırı |
| `DEFAULT_DURATION_WD = 1` | aynı yer | Bilgisiz görevin yer tutucu süresi |
| Tempo/ağırlık/itme kuralları | `production_plan.py → _compute_forecast`, `_weight_shares`, `_job_pace_totals`, `unplanned_duration` | Bölüm 2'nin tamamı |
| "Bitişi belirleyen" bayrağı | `production_plan.py → _mark_completion_driver` | 🚩 işareti |
| Finans eşiği `%90` | `meeting_brief.py → RISKY_COST_RATIO` | Riskli sınırı |
| Hayali kalem düşümü | `meeting_brief.py → _delivered_uncosted_material` | Bölüm 4 kuralı |
| Gerçek Başlangıç kanıtları | `production_plan.py → _first_progress_evidence` | Bölüm 1 tablosu |
| Arayüz metinleri (Öngörü Dayanağı vb.) | `white-app/projects/production-planning/production-planning.js` | Plan Detayı penceresi |

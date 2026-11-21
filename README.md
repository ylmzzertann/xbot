# XBot — X (Twitter) küfür tespit ve engelleme botu

Kendi X hesabında, belirlediğin arama kelimelerine ait **son N dakikadaki**
tweetleri tarayan; küfür/hakaret içerenleri bulan ve (senin izninle) o hesapları
engelleyen kişisel bir araç.

Resmî X API **kullanılmıyor**: program Playwright ile gerçek bir tarayıcı açıp
senin yerine arayüzde geziniyor.

> ⚠️ **Risk uyarısı:** Tarayıcı otomasyonu X kullanım şartlarına aykırı olabilir;
> hesabın kısıtlanabilir. Bu riski kabul ettiğin varsayılıyor. Program bu yüzden
> baştan sona "temkinli" tasarlandı: varsayılan mod hiçbir şeyi engellemeyen
> `dry-run`, sıkı saatlik/günlük limitler, işlemler arası rastgele bekleme,
> beyaz liste ve beklenmeyen bir ekran görülürse **anında durma**.
>
> Program bot algılamayı atlatmaya çalışmaz: stealth eklentisi, parmak izi
> gizleme, proxy döndürme, CAPTCHA çözücü **yoktur** ve eklenmeyecek. CAPTCHA
> veya doğrulama ekranı görülürse durur, ekran görüntüsü alır ve sana haber verir.

---

## İçindekiler

1. [Kurulum](#kurulum)
2. [İlk giriş](#i̇lk-giriş-bir-kez)
3. [Seçici kontrolü (önemli)](#seçici-kontrolü-önemli)
4. [Modlar ve komutlar](#modlar-ve-komutlar)
5. [Karar mantığı](#karar-mantığı)
6. [Kelime listelerini düzenleme](#kelime-listelerini-düzenleme-data)
7. [Zamanlanmış görev (ben yokken)](#zamanlanmış-görev-ben-yokken)
8. [Engellenenlerin tweet dosyası](#engellenenlerin-tweet-dosyası) ·
   [Raporlar ve yanlış engellemeyi geri alma](#raporlar-ve-yanlış-engellemeyi-geri-alma)
9. [Güvenlik kuralları](#güvenlik-kuralları-kodda-uygulanıyor)
10. [Testler](#testler)
11. [Sorun giderme](#sorun-giderme)
12. [Proje yapısı](#proje-yapısı)
13. [Varsayımlar](#varsayımlar)

---

## Kurulum

Python 3.11+ gerekir (bu proje 3.13 ile geliştirildi).

```bash
python -m pip install -r requirements.txt
```

```bash
python -m playwright install chromium
```

Ayar dosyanı oluştur (ilk kurulumda bir kez):

```bash
copy config.example.yaml config.yaml
```

`config.yaml` içindeki `search_queries` (aranacak kelimeler) ve `target_names`
(hedef isim parçaları) listelerini kendine göre doldur. Bu dosya `.gitignore`
içindedir: senin kişisel ayarların.

Her şeyin yerinde olduğunu kontrol et:

```bash
python -m xbot doctor
```

---

## İlk giriş (bir kez)

```bash
python -m xbot login
```

Görünür bir tarayıcı açılır. **Girişi sen yaparsın.** Program şifre sormaz,
görmez, kaydetmez; oturum yalnızca `paths.profile_dir` (varsayılan `.profile`)
klasöründe Chromium'un kendi çerezleri olarak kalır. O klasör `.gitignore`
içindedir ve kimseyle paylaşılmamalıdır.

Giriş algılanınca program kullanıcı adını yazar. İstersen `config.yaml` içine
`account_handle: "kullanici_adin"` yaz (sadece `sync-whitelist` biraz hızlanır).

---

## Seçici kontrolü (önemli)

X arayüzü sık değişir. Program tüm CSS/`data-testid` seçicilerini tek dosyada
tutar ([xbot/selectors.py](xbot/selectors.py)) ve bunları **canlı sayfada**
doğrulayabilir:

```bash
python -m xbot check-selectors
```

```bash
python -m xbot check-selectors --menu
```

İkincisi bir tweetin `...` menüsünü de açıp "Engelle" satırının yerinde
olduğunu kontrol eder — **hiçbir şeyi engellemez**, menüyü Escape ile kapatır.

Bir seçici "EKSİK" çıkarsa: `xbot/selectors.py` dosyasındaki ilgili satırı
güncelle. Her öğe için yedek seçiciler de var; ilk bulunan kullanılır.

> Not: Bu seçiciler X'in bilinen `data-testid` değerlerine dayanır ve yerel bir
> "X taklidi" sayfası üzerinde gerçek tarayıcıyla test edilir
> ([tests/test_browser_integration.py](tests/test_browser_integration.py)).
> Ama X oturumu olmadan canlı doğrulama yapılamaz; bu yüzden **ilk kurulumda
> `check-selectors` çalıştırmak senin adımın.**

---

## Modlar ve komutlar

### `run` — tarama

```bash
python -m xbot run
```

**Varsayılan `dry-run`:** hiçbir hesabı engellemez. Ne yapacağını söyler,
şüphelileri veritabanına yazar.

```bash
python -m xbot run --auto
```

`--auto`: YÜKSEK kararlı hesapları **gerçekten engeller** (limitler ve beyaz
liste her zaman geçerli). Etkileşimli çalıştırırsan 3 saniye geri sayım verir.

Faydalı seçenekler:

| Seçenek | Ne yapar |
|---|---|
| `-q "kelime"` | Sadece o kelimeyi tarar (birden çok verilebilir) |
| `--dakika 120` | Zaman penceresini değiştirir (varsayılan 60) |
| `--headless` | Tarayıcıyı gizli çalıştırır (zamanlanmış görev için) |
| `--gorunur` | Tarayıcıyı görünür açar |
| `--rapor` | Tur sonunda HTML + CSV rapor üretir |

### `phrase` — yazdığın kelime/cümleyle engelle

Her çalıştırmada **o an ne yazarsan** onu arar. Engellemeden önce bulunanları
gösterir; engelleme ancak sen onaylayınca başlar.

```bash
python -m xbot phrase
```

```
Engellemek istediğin kelime ya da cümleyi yaz > okan istifa

          'okan istifa' — son 60 dakikada bulunanlar
 #  Hesap      Yazdığı                        Zaman             Küfür    Durum
 1  @kizgin1   Okan istifa artık yeter        21.09.2026 14:03  TEMİZ    engellenecek
 2  @kizgin2   OKAN İSTİFA!!! siktir git      21.09.2026 13:58  YÜKSEK   engellenecek
               (+1 tweet daha)
 3  @dostum    okan istifa etsin bence        21.09.2026 13:40  TEMİZ    beyaz listede (atlanır)
4 tweet, 3 hesap bulundu → 2 hesap engellenecek | 1 beyaz listede

e = hepsini engelle, ç = bazılarını çıkar, v = vazgeç > ç
Çıkarılacak numaralar (ör: 2,5,7-9) > 1
Çıkarılanlar: 1 → engellenecek hesap: 1
e = hepsini engelle, ç = bazılarını çıkar, v = vazgeç > e

Engellenecek hesaplar: @kizgin2
1 hesap ENGELLENECEK. Başlamak için evet yaz > evet
[1/1] @kizgin2 engelleniyor...
   ✓ engellendi
```

* İfadeyi komutla birlikte de verebilirsin: `python -m xbot phrase "okan istifa"`
* Yazım oyunları da yakalanır: "OKAN İSTİFA", "okan istifaaa", "#OkanIstifa",
  "o.k.a.n istifa".
* Tek kelimeler varsayılan olarak kelime içinde de aranır ("hakem" →
  "hakemler"). Sadece tam kelime için `--tam-kelime`.
* **Son onay için mutlaka `evet` yazılmalı**; başka her cevap iptal sayılır.
* Beyaz listedekiler, zaten engelliler ve kendi hesabın listede görünür ama
  atlanır. "Küfür" sütunu, tweetin normal küfür dedektörüne göre durumunu
  bilgi olarak gösterir.
* Limitler burada da geçerli: onayladığın hesap sayısı kalan limitten fazlaysa,
  fazlası `review` listesine eklenir; limit açılınca oradan engellersin.
* Tweet engelleme anında silinmişse o hesap atlanır, kalanlara devam edilir.

| Seçenek | Ne yapar |
|---|---|
| `--dakika 180` | Zaman penceresi (varsayılan config'teki 60) |
| `--tam-kelime` | Tek kelimeyi sadece tam kelime olarak ara |
| `--kaydirma 30` | Daha çok sonuç için daha fazla kaydır |
| `--sadece-goster` | Sadece listele, hiçbir şey sorma/engelleme |
| `--gorunur` / `--headless` | Tarayıcı görünür mü gizli mi |

### `review` — şüphelileri tek tek incele

```bash
python -m xbot review
```

Her şüpheli tweet için: `e` engelle, `a` atla, `t` temizle (bir daha sorma),
`q` çık. Tarayıcı ancak "engelle" dediğinde açılır.

### Diğer komutlar

| Komut | İşi |
|---|---|
| `check "metin"` | Tek bir metni dedektörden geçirir (tarayıcı açmaz) |
| `check-file dosya.txt` | Her satırı tweet sayıp toplu dener |
| `words` / `words --listele` | Kelime listelerinin durumu |
| `config-show` | Ayarları doğrular ve gösterir |
| `doctor` | Kurulum kontrolü (Python, Playwright, Chromium, listeler, oturum) |
| `list-blocked` | Engellenenleri kanıtlarıyla listeler |
| `blocked-tweets` / `blocked-tweets --ac` | Engellenenlerin yazdıklarını gösterir (dosyayı açar) |
| `mark-unblocked <#>` | X'te engeli kaldırdığın kaydı işaretler |
| `stats` | Özet istatistikler + limit durumu |
| `report --ac` | HTML + CSV rapor üretir (ve açar) |
| `sync-whitelist` | Takip ettiklerini beyaz listeye ekler |
| `task-command` | Zamanlanmış görev komutunu yazdırır |

Çıkış kodları: `0` başarılı, `1` kullanım hatası, `2` ayar/kurulum hatası,
`4` güvenlik nedeniyle durdu, `5` başka bir çalışma sürüyor.

---

## Karar mantığı

Program iki seviye üretir. **Sadece YÜKSEK otomatik engellenebilir.**

| Bulunan | Hedef isim var | Hedef isim yok |
|---|---|---|
| **güçlü** küfür (`siktir`, `orospu`, `amına koyayım`) | YÜKSEK | YÜKSEK |
| **hafif** hakaret (`salak`, `dangalak`) | YÜKSEK | ŞÜPHELİ |
| **belirsiz** ifade (`amk`, `aq`, `hayvan`) | YÜKSEK | ŞÜPHELİ |
| eşleşme yok | TEMİZ | TEMİZ |

Seviyeyi **sadece düşüren** iki fren var:

1. **Olumlu bağlam freni:** tweette `gol`, `helal`, `kral`, `tebrik` gibi bir
   kelime varsa, *güçlü olmayan* eşleşmeler YÜKSEK'e çıkarılmaz.
   → `"okan buruk amk kral adam ya"` = ŞÜPHELİ, `"okan buruk amk"` = YÜKSEK.
2. **`high_requires_target: true`** yaparsan hedef isim geçmeyen hiçbir tweet
   YÜKSEK olmaz (en temkinli ayar).

`detection.ambiguous_with_target: suspect` ve `mild_with_target: suspect`
yaparak "hedef isim + belirsiz/hafif" kombinasyonlarını da engellemeden
çıkarabilirsin.

### Küfürden kaçma oyunlarına karşı normalizasyon

| Yazım | Nasıl görülür |
|---|---|
| `SİKTİR`, `Siktir` | Türkçe kurallarıyla küçültme (`İ`→`i`, `I`→`ı`) |
| `YAVŞAK` | `yavsak` (ş→s, ç→c, ğ→g, ö→o, ü→u) |
| `amkkkkk` | `amk` (tekrarlar sadeleşir) |
| `s1kt1r`, `$erefsiz`, `am@na` | rakam/sembol → harf |
| `a.m.k`, `s_i_k` | araya konan işaretler silinir |
| `s*ktir` | joker: `*` herhangi bir harf sayılır (sınırlı sayıda) |
| `s i k t i r` | harf harf yazımlar birleştirilir |
| `@OkanBuruk`, `#Galatasaray` | işaretler atılır |
| görünmez karakterler, emoji | atılır |

**Kritik ayrıntı — `ı`/`i` ayrımı:** "sıkıntı", "sık sık", "sıkıldım" gibi masum
kelimeler `sik` köküyle karışmasın diye noktasız `ı` ayrı tutulur. Bu ayrımı
isteyen kökler listede `keep_i` bayrağını taşır.

---

## Kelime listelerini düzenleme (`data/`)

Dosyalar düz metin ve UTF-8. `#` ile başlayan satırlar yorum. Program her
çalıştığında yeniden okur; kod değiştirmen gerekmez.

### `data/profanity.txt` — küfür kökleri

```
kök | bayrak, bayrak
```

| Bayrak | Anlamı |
|---|---|
| `strong` | Açık ve net küfür (**varsayılan**). Tek başına YÜKSEK. |
| `mild` | Hafif hakaret. Tek başına ŞÜPHELİ. |
| `ambiguous` | Belirsiz, sevinçle de kullanılabilir. Tek başına ŞÜPHELİ. |
| `exact` | Sadece tam kelime olarak eşleşir (`amk` evet, `adamki` hayır). |
| `keep_i` | `ı`/`i` ayrımını korur (`sik` ≠ `sık`). |

Birden fazla kelimeden oluşan kökler (`amına koyayım`) boşluklar silinerek aranır.

### Diğer listeler

| Dosya | İşi |
|---|---|
| `data/allowlist_words.txt` | Masum kelimeler: kök bu kelimenin içinde kalırsa sayılmaz (`götür` → "götürdüm" temiz) |
| `data/allowlist_phrases.txt` | Masum kalıplar: `eşek arısı`, `kaşar peyniri`, `hayvan gibi`, `mal sahibi`… |
| `data/positive_context.txt` | Sevinç/olumlu bağlam kelimeleri (fren) |
| `data/whitelist.txt` | **Asla engellenmeyecek hesaplar** (her satıra bir kullanıcı adı) |

### Yanlış pozitif gördüğümde ne yapmalıyım?

1. Kök çok mu genel? → köke `exact` veya `keep_i` ekle.
2. Belirli bir masum kelimede mi çıkıyor? → `allowlist_words.txt`'e ekle.
3. Belirli bir ifadede mi çıkıyor? → `allowlist_phrases.txt`'e ekle.
4. Kelime bağlama çok mu bağlı? → ağırlığını `ambiguous` yap ya da kökü sil.

Her değişiklikten sonra:

```bash
python -m pytest -q
```

---

## Zamanlanmış görev (ben yokken)

Hazır komutu program yazdırır:

```bash
python -m xbot task-command --dakika 60
```

### Windows Görev Zamanlayıcı — arayüzle (adım adım)

1. Başlat → **Görev Zamanlayıcı** (Task Scheduler) → **Görev Oluştur…**
   (basit görev değil, "Görev Oluştur").
2. **Genel** sekmesi: Ad `XBot`. "Yalnızca kullanıcı oturum açtığında çalıştır"
   seçili kalsın (tarayıcı gerekiyor). "En yüksek ayrıcalıklarla çalıştır"a
   gerek **yok**.
3. **Tetikleyiciler** → Yeni: "Zamanlamaya göre" → Günlük → başlangıç saati →
   **Gelişmiş ayarlar** → "Görevi şu sıklıkta yinele: 1 saat" → "Süre: Süresiz".
4. **Eylemler** → Yeni → Program/komut dosyası:
   `C:\Users\<kullanıcı>\OneDrive\Desktop\XBot\scripts\xbot_dry_run.cmd`
   (Başlangıç yeri: `C:\Users\<kullanıcı>\OneDrive\Desktop\XBot`)
5. **Koşullar**: "Yalnızca bilgisayar AC gücündeyse" isteğe bağlı; "Görevi
   çalıştırmak için bilgisayarı uyandır" kapalı kalsın.
6. **Ayarlar**: "Görev zaten çalışıyorsa yeni örnek başlatma" seçili olsun
   (program ayrıca kilit dosyası kullanır, iki çalışma çakışmaz).

Komut satırından tek satırda:

```bash
schtasks /Create /TN "XBot" /SC MINUTE /MO 60 /TR "C:\Users\ertan\OneDrive\Desktop\XBot\scripts\xbot_dry_run.cmd" /F
```

Silmek için:

```bash
schtasks /Delete /TN "XBot" /F
```

**Önce günlerce `xbot_dry_run.cmd` ile çalıştır.** Raporları beğenirsen görevi
`scripts\xbot_auto.cmd` dosyasına çevir (gerçek engelleme).

### Linux / macOS (cron)

```bash
crontab -e
```

```
0 * * * * cd /yol/XBot && ./scripts/xbot_cron.sh
```

### Görev çalışırken ne olur?

* Çıktılar `logs/gorev.log` ve `logs/xbot.log` dosyalarına yazılır.
* Aynı anda ikinci bir çalışma başlamaz (`logs/xbot.lock`).
* Program güvenlik nedeniyle durursa: masaüstü uyarısı verilir ve
  `logs/SON_HATA.txt` yazılır (`notifications` ayarlarıyla kapatılabilir).
* `--rapor` sayesinde her turda `reports/son-rapor.html` güncellenir.

---

## Engellenenlerin tweet dosyası

Engellenen her hesabın yazdıkları tek bir dosyada **birikir** (eski kayıtlar
silinmez):

```
kayitlar/engellenen_tweetler.csv
```

* Hangi yoldan engellenirse engellensin (`phrase`, `run --auto`, `review`)
  dosyaya yazılır.
* Sütunlar: kayıt zamanı, hesap, görünen ad, tweet id, **tweet metni**, tweet
  linki, tweet zamanı, sebep (ör. `ifade: "okan istifa"` ya da `siktir`), mod.
* `phrase` ile aynı hesabın birden fazla tweeti bulunduysa hepsi yazılır.
* Excel'de çift tıklayınca doğru açılır (UTF-8 + `;` ayırıcı); satır içi
  alt satırlar ve noktalı virgüller korunur.
* Yol `config.yaml` → `paths.blocked_tweets` ile değiştirilebilir.
* Dosyada **başkalarının yazdıkları** olduğu için `.gitignore` içindedir.

```bash
python -m xbot blocked-tweets
```

```bash
python -m xbot blocked-tweets --ac
```

---

## Raporlar ve yanlış engellemeyi geri alma

```bash
python -m xbot report --ac
```

`reports/` altında: `son-rapor.html` (okunaklı tablo, koyu tema uyumlu),
`engellenenler-*.csv` ve `supheliler-*.csv` (Excel uyumlu, UTF-8 BOM + `;`).

Her engelleme kaydında **geri almak için gereken her şey** var: hesap adı,
tweet metni, tweet linki, tweet zamanı, eşleşen kural, gerekçe, mod ve zaman.

Yanlış bir engelleme gördüysen:

```bash
python -m xbot list-blocked
```

1. `https://x.com/<hesap>` sayfasında "Engeli kaldır" (bunu **sen** yaparsın;
   program engel kaldırmıyor).
2. Kaydı işaretle:

```bash
python -m xbot mark-unblocked 3 --not "yanlış pozitif: sıkıntı kelimesi"
```

Böylece o hesap "engelli" sayılmaz ve limit sayacından düşer.

---

## Güvenlik kuralları (kodda uygulanıyor)

| Kural | Nerede |
|---|---|
| Varsayılan `dry-run`; gerçek engelleme yalnızca `--auto` veya `review` onayıyla | [cli.py](xbot/cli.py), [actions.py](xbot/actions.py) |
| Saatte 10 / günde 40 engelleme (config'ten); işlem arası 8–25 sn, kaydırma arası 2–5 sn rastgele bekleme | [ratelimit.py](xbot/ratelimit.py) |
| CAPTCHA, doğrulama, giriş ekranı, "hesabınız kısıtlandı" veya beklenmeyen sayfa → **anında dur**, ekran görüntüsü + HTML kaydet, haber ver | [safety.py](xbot/safety.py) |
| Bot algılamayı atlatma tekniği yok | [browser.py](xbot/browser.py) |
| Seçici bulunamazsa sessizce devam etme: dur, logla, kanıt kaydet | [browser.py](xbot/browser.py) `require_first` |
| Beyaz listedeki hesap hiçbir koşulda engellenmez (limitten de önce bakılır) | [actions.py](xbot/actions.py) |
| Aynı anda iki çalışma olmaz; aynı tweet/hesap tekrar işlenmez | [lock.py](xbot/lock.py), [storage.py](xbot/storage.py) |
| Her engellemede tam kanıt kaydı | [storage.py](xbot/storage.py), [report.py](xbot/report.py) |
| İlk çalıştırmalarda tarayıcı görünür (`headless: false`) | [config.yaml](config.example.yaml) |

Şifre/token hiçbir yere yazılmaz; program kimlik bilgisi sormaz. Oturum yalnızca
tarayıcı profil klasöründedir.

---

## Testler

```bash
python -m pytest -q
```

538 test + 1 atlanan (Playwright yoksa tarayıcı testleri de atlanır). Öne çıkanlar:

* **Yanlış pozitif korpusu** ([tests/test_detection.py](tests/test_detection.py)):
  "sıkıntı yok", "klasik maç", "psikolojik üstünlük", "aşık oldum", "seni maça
  götürdüm", "eşek arısı", "hayvan gibi oynadı maşallah", "adamına göre",
  "2-0 kazandık" gibi 50 masum cümle **TEMİZ** kalmalı; "amk gol" gibi sevinç
  ifadeleri **asla engellenmemeli**.
* **Gerçek tarayıcı testleri**
  ([tests/test_browser_integration.py](tests/test_browser_integration.py)):
  yerel bir "X taklidi" HTML sayfası üzerinde gerçek (headless) Chromium ile
  oturum açma, tweet okuma, kaydırma, `...` → Engelle → onay akışı, kanıt
  kaydı, beyaz liste ve "kısıtlandı" sayfasında durma test edilir. X'e hiçbir
  istek gitmez.
* Limit/kilit/beyaz liste frenleri, SQLite kayıtları, rapor üretimi, CLI
  komutları.

### Elle test listesi (tarayıcı gerektiren, bir kez yapılması iyi olan)

1. `python -m xbot doctor` → her şey "tamam" mı?
2. `python -m xbot login` → giriş algılanıyor mu, kullanıcı adı doğru mu?
3. `python -m xbot check-selectors --menu` → bütün zorunlu seçiciler yerinde mi?
4. `python -m xbot run --gorunur` → tarayıcı arama sayfasını açıyor, kaydırıyor,
   özet mantıklı mı? (dry-run, hiçbir şey engellenmez)
5. `python -m xbot report --ac` → rapor açılıyor mu?
6. Bir tanıdığını `data/whitelist.txt`'e ekle, o hesabın tweeti YÜKSEK bile
   olsa atlandığını `logs/xbot.log` içinde gör.
7. Sadece hazır olduğunda: `python -m xbot run --auto -q "tek bir kelime"`
   ve `python -m xbot list-blocked` ile sonucu kontrol et.

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `Playwright kurulu değil` | `python -m pip install playwright` ve `python -m playwright install chromium` |
| Türkçe karakterler bozuk görünüyor | `set PYTHONUTF8=1` (scripts/*.cmd bunu kendisi yapar) |
| `Oturum açık değil` | `python -m xbot login` ile yeniden gir; `.profile` klasörünü silme |
| `Arayüz öğesi bulunamadı` | `python -m xbot check-selectors --menu`, sonra `xbot/selectors.py`'ı güncelle; `logs/screenshots` altındaki HTML dosyası yardımcı olur |
| `Başka bir XBot çalışması sürüyor` | Gerçekten çalışmıyorsa `logs/xbot.lock` dosyasını sil |
| CAPTCHA/doğrulama ekranı | Program durur. Tarayıcıyı elle açıp doğrulamayı **sen** yap, bir süre bekle, sonra tekrar dene. Limitleri düşürmeyi düşün. |
| Engelleme olmuyor | `config-show` ile modu kontrol et (`dry-run` mı?), `stats` ile limitleri kontrol et |
| Çok fazla şüpheli çıkıyor | `data/profanity.txt`'te bazı `ambiguous` kökleri sil ya da `positive_context.txt`'i genişlet |
| Zamanlanmış görev çalışmıyor | Görev Zamanlayıcı'da "Yalnızca kullanıcı oturum açtığında çalıştır" seçili olmalı; `logs/gorev.log` dosyasına bak |

---

## Proje yapısı

```
XBot/
├── config.example.yaml       # örnek ayarlar (kopyala → config.yaml)
├── data/                     # düzenlenebilir kelime listeleri
├── examples/ornek_tweetler.txt
├── scripts/                  # zamanlanmış görev sarmalayıcıları
│   ├── xbot_dry_run.cmd      #   Windows: engellemeyen tur
│   ├── xbot_auto.cmd         #   Windows: gerçek engelleme
│   └── xbot_cron.sh          #   Linux/macOS
├── xbot/
│   ├── cli.py                # komutlar (ekrana yazdırma)
│   ├── app.py                # parçaları birleştiren uygulama katmanı
│   ├── config.py             # ayar yükleme + doğrulama
│   ├── models.py             # Tweet, Match, Verdict, Decision
│   ├── errors.py             # StopRun / SafetyStop / SelectorNotFound …
│   ├── safety.py             # beklenmeyen sayfa tespiti (anında dur)
│   ├── browser.py            # Playwright oturumu, profil, kanıt kaydı
│   ├── selectors.py          # TÜM CSS/data-testid seçicileri
│   ├── scraper.py            # arama sayfasını tarama, tweet ayrıştırma
│   ├── timefilter.py         # son N dakika filtresi
│   ├── actions.py            # engelleme akışı (menü → Engelle → onay)
│   ├── ratelimit.py          # saatlik/günlük limit + rastgele bekleme
│   ├── whitelist.py          # asla engellenmeyecek hesaplar
│   ├── lock.py               # tek çalışma kilidi
│   ├── storage.py            # SQLite kayıtlar
│   ├── runner.py             # tur yönetimi
│   ├── report.py             # CSV + HTML rapor
│   ├── phrase_hunt.py        # "phrase": gruplama, numara seçimi, limit planı
│   ├── evidence.py           # engellenenlerin tweet dosyası (CSV)
│   ├── notify.py             # masaüstü bildirimi
│   ├── logging_setup.py
│   └── detector/
│       ├── base.py           # Detector arayüzü + eklenti kaydı
│       ├── normalizer.py     # Türkçe metin normalizasyonu
│       ├── matcher.py        # kök eşleştirme motoru
│       ├── profanity.py      # kelime listesi tabanlı dedektör
│       ├── target.py         # hedef isim dedektörü
│       ├── context.py        # olumlu bağlam dedektörü
│       ├── phrase.py         # kullanıcının yazdığı ifadeyi arayan dedektör
│       └── engine.py         # kararı birleştiren motor
└── tests/                    # 538 test
```

### Sonraki adımlar için mimari hazır

İleride eklenecekler için kod bilinçli olarak ayrıştırıldı:

* **Yapay zeka tabanlı dedektör:** `Detector` arayüzünü uygulayıp
  `register_detector` ile kaydetmek yeterli; motor içini bilmiyor.
* **Engelleme yerine sessize alma:** `BlockUi` protokolüne kardeş bir `MuteUi`
  eklenebilir (`selectors.MENU_MUTE` hazır).
* **Yanıt (reply) taraması:** `TweetSource` protokolüne yeni bir kaynak.
* **Hesap özellikleriyle puanlama, Telegram/e-posta bildirimi, web paneli,
  kategori bazlı kural setleri, çoklu hesap:** sırasıyla yeni bir dedektör,
  `notify.py` içine yeni bir yol, `app.py` üzerine yeni bir arayüz, ayrı liste
  dosyaları ve ayrı profil klasörleri ile çözülür.

---

## Varsayımlar

Belirsiz noktalarda yapılan makul varsayımlar:

1. **İki karar seviyesi, üç kelime ağırlığı.** İstenen HIGH/SUSPECT kararının
   üstüne kelime ağırlığı olarak üç kademe eklendi (`strong`/`mild`/
   `ambiguous`), böylece "siktir" ile "salak" aynı kefeye girmiyor.
2. **"Küfür + hedef isim = YÜKSEK"** kuralı varsayılan olarak uygulanıyor, fakat
   **sevinç freni** eklendi: olumlu bağlam kelimesi varsa güçlü olmayan
   eşleşmeler YÜKSEK'e çıkmaz ("amk gol", "okan buruk amk kral adam").
3. **`ı`/`i` ayrımı** yanlış pozitifin en büyük kaynağı olduğu için `keep_i`
   bayrağı eklendi. `SIKTIR` (ASCII klavye, büyük harf) Türkçe kurala göre
   `sıktır` olduğundan listeye ayrıca `sıktır` kökü de eklendi.
4. **Tek kelimelik kökler, kelimeler birleştirilerek aranmaz** ("klasik tirat" →
   "siktir" gibi uydurma eşleşmeleri önlemek için). Aralıklı yazım
   (`s i k t i r`) için yalnızca 1–2 harflik kelime dizileri birleştirilir.
5. **Bağlama çok bağlı kelimeler listeye alınmadı** (`rezil`, `satılmış`,
   `hain`, `it`, `hıyar`, `top`): futbol tweetlerinde çok fazla şüpheli
   üretiyorlardı. İstersen `ambiguous` olarak ekleyebilirsin.
6. **Masum kalıp listesi** (`allowlist_phrases.txt`) istenmemişti ama eklendi:
   "eşek arısı", "kaşar peyniri", "hayvan gibi", "mal sahibi" gibi ifadeler tek
   kelime istisnasıyla çözülemiyordu.
7. **Tarihi okunamayan tweet pencere dışında sayılır.** Yani işlenmez. Böylece
   eski bir tweet yüzünden yanlış engelleme riski oluşmaz.
8. **Kaydırma, pencere bitince durur:** üst üste 3 eski tweet görülürse ya da
   2 kaydırmada yeni tweet gelmezse tarama biter (`max_scrolls_per_query` üst
   sınır olarak kalır).
9. **Engellemenin doğrulaması** onay penceresinin kapanmasıyla yapılır. Kapanmazsa
   program durur ve kaydı yazmaz; hesabı elle kontrol etmen istenir.
10. **`review` komutu** şüpheli tweetin kendi sayfasına giderek engeller (arama
    sayfası o tweeti artık göstermeyebilir).
11. **Engel kaldırma (unblock) otomatikleştirilmedi.** Bilinçli: program yanlış
    pozitifleri geri almak için kanıt tutar, engeli kaldırmayı sen yaparsın;
    `mark-unblocked` sadece kaydı günceller.
12. **Masaüstü bildirimi** ek paket gerektirmeyen yollarla yapılır (Windows'ta
    kendi kendine kapanan uyarı penceresi); hiçbiri çalışmazsa olay
    `logs/SON_HATA.txt` dosyasına yazılır.
13. **Seçiciler canlı X sayfasında doğrulanamadı** (oturum gerektiriyor ve bu
    senin hesabın). Bunun yerine: bilinen `data-testid` değerleri + her öğe için
    yedek seçiciler + yerel taklit sayfa üzerinde gerçek tarayıcı testleri +
    `check-selectors` komutu. İlk kurulumda `check-selectors` çalıştırmak senin
    adımın.
15. **`phrase` araması:** ifade X'te aranır (çok kelimeliyse tırnak içinde,
    tam ifade olarak), sonra her tweet programın kendi Türkçe normalizasyonuyla
    **yeniden kontrol edilir**; X'in gevşek sonuçları (kelimeler ayrı yerlerde,
    profil adında vb.) listeye girmez.
16. **Hesap başına tek engelleme:** aynı hesabın birden fazla tweeti bulunursa
    hesap bir kez engellenir, eşleşen tweetlerinin hepsi dosyaya yazılır.
17. **Dosyaya yazılan "yazdıkları":** taramada bulunan ve engellemeye sebep olan
    tweetlerdir. Hesabın profilindeki tüm tweetler toplanmaz (daha çok istek ve
    daha çok kişisel veri demek olurdu).
18. **`phrase` de limitlere tabidir** (saatlik/günlük). Onaylanıp limite
    takılan hesaplar kaybolmaz, `review` listesine eklenir.
19. **Tweet sayfada görünmüyorsa** (X aşağı kaydırılınca eski tweetleri sayfadan
    siler) program tweetin kendi sayfasına gider. Tweet o arada silinmişse
    sadece o hesap atlanır; tüm tur durmaz.

20. **CLI komut ve seçenek adları İngilizce** (spesifikasyondaki gibi), ekrana
    çıkan her şey Türkçe. Kod, değişken ve kod içi yorumlar İngilizce/ASCII;
    kullanıcıya görünen metinler tam Türkçe.

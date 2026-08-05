# ShaniShvilin Catalog

הקטלוג של **שני שבילין**. הוא עונה על שאלה אחת: **מי**.

- אילו אפליקציות מוצגות בחנות.
- אילו אפליקציות מקבלות גישה לאינטרנט.
- מה החתימה ו-versionCode המינימלי של כל אחת.
- מאיזה מצב סינון כל אפליקציה זמינה.

**מה לחסום בתוך** אפליקציה שכבר אושרה זו שאלה שנייה, והתשובה עליה יושבת כאן
תחת `policies/`, בפורמט של
[KDroidDatabase](https://github.com/kdroidFilter/KDroidDatabase) - כך שאפשר
להעתיק משם מסמך כמו שהוא.

הריפו הזה הוא מקור הנתונים החי של האפליקציה. **דחיפה ל-`main` מעדכנת מכשירים
בשטח תוך שש שעות לכל היותר, בלי גרסה חדשה של האפליקציה.**

---

## מבנה

```
apps/<category>/<packageName>.json         מי - הקטלוג
policies/<category>/<packageName>.json     מה - מה חסום בתוך אפליקציה מאושרת

catalog.json      catalog.version                         ← נבנים, לא נערכים ביד
policies.json                                             ← נבנה, לא נערך ביד
signatures.json                                           ← החתימות, base64
catalog.json.sig  policies.json.sig                       ← אותן חתימות כבייטים
```

קובץ אחד לאפליקציה, מסודר לפי קטגוריה. זה מונע קונפליקטי merge ומאפשר PR ממוקד.
הקבצים שבשורש הם התוצר, והם היחידים שהאפליקציה מורידה.

קטגוריות: `navigation`, `mail`, `communication`, `music-audio`, `video`,
`torah`, `productivity`, `tools`, `finance`, `health-fitness`, `news`,
`governement`, `home`, `system`.

## סכימה

ראה [`schema/catalog-entry.schema.json`](schema/catalog-entry.schema.json).

```json
{
  "packageName": "com.waze",
  "displayName": { "he": "וייז", "en": "Waze" },
  "category": "NAVIGATION",
  "minimumVersionCode": 1030416,
  "sha256": "3a7f...c91d",
  "availableInStore": true,
  "grantsNetworkAccess": true,
  "minUserMode": "NAVIGATION_ONLY",
  "flags": { "isRecommendedInStore": true },
  "source": { "type": "APKPURE", "id": "com.waze" }
}
```

### שדות

| שדה | חובה | תפקיד |
|---|---|---|
| `packageName` | כן | שם החבילה |
| `displayName` | כן | שם מוצג לפי שפה. `he` ו-`en` לפחות |
| `category` | כן | קטגוריה |
| `minimumVersionCode` | כן | מונע שנמוך לגרסה ישנה עם פחות הגנות |
| `sha256` | כן | **SHA-256 של חתימת ה-APK.** 64 תווי hex קטנים |
| `availableInStore` | לא (ברירת מחדל `true`) | האם מוצגת בחנות |
| `grantsNetworkAccess` | לא (ברירת מחדל **`false`**) | האם נכנסת למנהרה |
| `minUserMode` | לא (ברירת מחדל `MOST_OPEN`) | המצב המינימלי שממנו זמינה |
| `flags` | לא | אזהרות תוכן וסיכון |
| `source` | לא | מאיפה החנות מורידה |

**`grantsNetworkAccess` ברירת מחדל `false` בכוונה.** גישה לרשת היא opt-in.

**`availableInStore` ו-`grantsNetworkAccess` נפרדים בכוונה.** אפשר להציג בחנות
אפליקציה offline לגמרי (למשל Musicolet) בלי לתת לה רשת.

## איך משיגים `sha256`

```bash
./tools/compute-signature.sh com.waze
```

או ידנית:

```bash
adb shell pm path com.waze
adb pull <path> app.apk
apksigner verify --print-certs app.apk | grep -i "SHA-256 digest"
```

> **אל תעתיק את הערכים מהגרסאות הישנות.** הן השתמשו ב-SHA-1 עם באג ריפוד
> (`Integer.toHexString` בלי `%02x`), ולכן הערכים שם באורכים 37 עד 40 תווים
> ואינם ניתנים להשוואה לשום כלי סטנדרטי.

## מצבי סינון

| מצב | רמה | מה זמין |
|---|---|---|
| `OFFLINE` | 0 | שום אפליקציה לא מקבלת רשת |
| `LOCAL_ONLY` | 1 | רשת מקומית בלבד |
| `NAVIGATION_ONLY` | 2 | ניווט בלבד |
| `NAVIGATION_AND_MAIL_ONLY` | 3 | ניווט + דואר |
| `REDUCED_RISK` | 4 | קטגוריות מהימנות בלבד |
| `MOST_OPEN` | 5 | כל מה שבקטלוג |

אפליקציה זמינה כאשר **המצב הנוכחי >= `minUserMode` שלה**.

## דגלים

| דגל | משמעות |
|---|---|
| `hasUnmodestImage` | תוכן חזותי לא צנוע. דורש אישור מפורש, ומוחרג מ-`REDUCED_RISK` |
| `isPotentiallyDangerous` | סיכון טכני או אבטחתי. אותו טיפול |
| `requiresPlayStoreInstallation` | חייבת התקנה מ-Play |
| `isRecommendedInStore` | מודגשת בחנות |

## מדיניות רשת - `policies/`

הקטלוג מחליט מי נכנס למנהרה. המדיניות מחליטה מה מותר לו להגיע אליו בפנים.

```json
{
  "type": "Fixed",
  "packageName": "com.waze",
  "category": "NAVIGATION",
  "networkPolicy": {
    "mode": "BLACKLIST",
    "spec": { "type": "HostList", "hosts": ["*.waze.com", "support.google.com"] }
  },
  "minimumVersionCode": 1030416
}
```

שלושה סוגים: `Fixed` (מדיניות אחת), `ModeBased` (מדיניות לכל מצב סינון),
`MultiMode` (כמה וריאנטים לבחירת המשתמש בתוך מצב). מצבי רשת: `OFFLINE`,
`FULL_OPEN`, `WHITELIST`, `BLACKLIST`.

> **`*.` כאן אינו wildcard אמיתי.** בנתונים האלה `*.waze.com` פירושו
> `waze.com` ו-`www.waze.com` בלבד, ולא כל תת-דומיין. זה לא פירוש לטעם: כך
> קראה את זה הגרסה שאיתה הנתונים נבדקו, וקריאה כ-wildcard אמיתי חוסמת את
> `wig-il.waze.com` ומשאירה את ווייז פתוח בלי תוצאות חיפוש. הצד של האפליקציה
> ממומש ב-`KDroidHosts`. **המסקנה המעשית: כל מה שרוצים לחסום חייב להיות כתוב
> במפורש.**

## הוספת אפליקציה חדשה

לפני הכל, שתי החלטות **נפרדות**:

- `availableInStore` - האם היא מוצגת בחנות ואפשר להתקין אותה משם.
- `grantsNetworkAccess` - האם היא מקבלת גישה לרשת.

הן לא כרוכות זו בזו. אפליקציה offline לגמרי (Musicolet) מוצגת בחנות בלי רשת;
אפליקציה שמותקנת ידנית או מגיעה עם המכשיר (מפות, מזג אוויר) מקבלת רשת בלי
להופיע בחנות. **חבילה שאינה בקטלוג אינה מקבלת כלום**, לא משנה מה כתוב במדיניות
שלה.

### שלב 1: להשיג את טביעת האצבע של החתימה

זה השדה היחיד שאי אפשר לנחש, והוא מה שמונע מאפליקציה מזויפת בעלת אותו שם חבילה
לקבל רשת.

```bash
# האפליקציה מותקנת על מכשיר מחובר:
./tools/compute-signature.sh com.example.app

# או מקובץ APK שיש לך:
apksigner verify --print-certs app.apk | grep -i "SHA-256 digest"
```

התוצאה היא 64 תווי hex קטנים. **אל תעתיק ערכים מהגרסאות הישנות של המוצר** - הן
השתמשו ב-SHA-1 עם באג ריפוד, והערכים שם באורך 37 עד 40 תווים.

### שלב 2: לכתוב את קובץ הקטלוג

`apps/<category>/<packageName>.json` - שם הקובץ חייב להיות שם החבילה, והתיקייה
חייבת להתאים ל-`category` שבתוכו. ה-CI בודק את שניהם.

```json
{
  "packageName": "com.example.app",
  "displayName": { "he": "שם בעברית", "en": "English name" },
  "category": "NAVIGATION",
  "minimumVersionCode": 1030416,
  "sha256": "03637f6c...8807d7",
  "availableInStore": true,
  "grantsNetworkAccess": true,
  "minUserMode": "NAVIGATION_ONLY",
  "flags": { "isRecommendedInStore": true },
  "source": { "type": "APKPURE", "id": "com.example.app" }
}
```

`minUserMode` הוא המסלול המינימלי שממנו האפליקציה זמינה. אפליקציה זמינה כאשר
**המסלול הנוכחי במכשיר >= `minUserMode` שלה**.

#### מאיפה החנות מורידה

| `type` | מה קורה בפועל |
|---|---|
| `APKPURE` | מוריד. מנסה XAPK ואז APK, כי חבילות split מגיעות רק כ-XAPK |
| `FDROID` | מוריד דרך ה-index הרשמי |
| `DIRECT_URL` | מוריד מהכתובת. **חייבת להיות https** |
| `APKCOMBO`, `APTOIDE`, `PLAY` | **מזוהים אך לא מורידים דבר** |

שלושת האחרונים חוזרים כ-`Unsupported` מה-resolver. רשומה כזאת עם
`availableInStore: true` תופיע בחנות ותיכשל בהתקנה. אם אין מקור שמוריד, עדיף
`availableInStore: false` והתקנה ידנית.

> `com.moblin.israeltrain` נמצא כרגע במצב הזה בדיוק: `APKCOMBO`, מוצג בחנות,
> לא ניתן להורדה. ההערה בקובץ מסבירה למה - apkpure החזיר 410 עבור החבילה הזאת.

#### כמה אישורי חתימה לאותה חבילה

`additionalSha256` מקבל רשימה של טביעות אצבע נוספות. שימושי לאפליקציה שמותקנת
גם בגרסת debug וגם בגרסת release. **כל ערך שם הוא מפתח נוסף שרשאי לדבר בשם
החבילה**, ולכן הבנייה מזהירה על כל רשומה שמשתמשת בזה ומדפיסה כמה אישורים היא
מקבלת.

### שלב 3 (רשות): מדיניות רשת

`policies/<category>/<packageName>.json` קובע מה חסום **בתוך** אפליקציה שכבר
קיבלה רשת. אפליקציה בלי מסמך מדיניות מקבלת `FULL_OPEN` בתוך המנהרה - כלומר
הקטלוג לבדו הוא מה שפותח את הרשת, והמדיניות רק מצמצמת.

### שלב 4: לבנות, לחתום ולדחוף

```bash
./tools/release.sh
git add apps/ policies/ catalog.json catalog.version policies.json signatures.json *.sig
git commit -m "Add com.example.app"
git push
```

`release.sh` בונה את שני המסמכים, חותם עליהם, ומאמת את החתימות לפני שהוא מסיים.
אם הוא נכשל - שום דבר לא נדחף.

### שלב 5: לוודא על המכשיר

תוך שש שעות לכל היותר כל מכשיר מושך את השינוי לבד. כדי לא לחכות:

- **בחנות**: כפתור הרענון בסרגל העליון.
- **ב-ADB**:

```bash
adb shell am broadcast --user 0 \
  -n com.abaye.shanishvilin/com.abaye.shanishvilin.feature.admin.recovery.RecoveryReceiver \
  -a com.abaye.shanishvilin.action.RECOVERY \
  --es cmd sync --es token <token>
```

התשובה מדפיסה `catalogVersion`, `policyTag` ו-`lastSyncError`.

לבדוק שהאפליקציה אכן נכנסה לרשימת ההיתר:

```bash
adb logcat -d | grep -E "Allow list for|Rejected "
```

### מה משתבש, ואיך זה נראה

| מה רואים | הסיבה |
|---|---|
| `Rejected <pkg>: NOT_INSTALLED` | הרשומה תקינה, האפליקציה פשוט לא מותקנת |
| `Rejected <pkg>: SIGNATURE_MISMATCH` | ה-`sha256` אינו של הבנייה שמותקנת בפועל |
| `Rejected <pkg>: VERSION_TOO_LOW` | הגרסה המותקנת נמוכה מ-`minimumVersionCode` |
| האפליקציה בחנות אך ההתקנה נכשלת | `source` שאינו מוריד, או XAPK עם splits חסרים |
| הרשומה לא מופיעה כלל | `minUserMode` גבוה מהמסלול הנוכחי, או דגל שמחריג ב-`REDUCED_RISK` |

ה-CI דוחה JSON לא תקין, קובץ בקטגוריה שגויה, `sha256` שאינו 64 תווי hex, תוצר
שלא תואם למקור, וחתימה שאינה מאמתת.

## בנייה וחתימה

```bash
./tools/release.sh [path/to/private-key.pem]     # ברירת מחדל ../keys/shani-shvilin-catalog.pem
./tools/verify.sh                                # אימות בלבד, כמו שהמכשיר עושה
python tools/build_catalog.py --check            # התוצר תואם למקור?
python tools/build_policies.py --check
```

`catalog.version` הוא קובץ צד קטן שהאפליקציה מושכת לפני הקטלוג עצמו:

```json
{ "schemaVersion": 1, "entryCount": 14, "revision": "275a19108cba70b1" }
```

ה-`revision` הוא טביעת אצבע של **הנתונים בלבד**, לא של הקובץ. בנייה חוזרת ללא
שינוי תוכן מייצרת את אותו revision, והמכשיר לא מוריד כלום.

## מפתחות

החתימה היא ECDSA על עקומת P-256 עם SHA-256, והאימות במכשיר הוא חובה - לא best effort.

- `keys/signing-current.pub.pem`, `keys/signing-standby.pub.pem` - החצאים
  הציבוריים, ו-`keys/public-keys.hex` הוא בדיוק מה שמוצמד באפליקציה
  ב-`SyncWorker.PINNED_PUBLIC_KEYS`.
- **המפתחות הפרטיים אינם בריפו הזה ואינם ב-GitHub.** החתימה רצה מקומית על
  המכונה שמחזיקה אותם; ה-CI רק מאמת, ולכן אין כאן secret שאפשר לגנוב.
- שני מפתחות מוצמדים, נוכחי ומילואים, כדי שאפשר יהיה להחליף מפתח בלי לנתק
  מכשירים שנשארו על גרסה ישנה: חותמים במפתח המילואים, משחררים גרסה שמצמידה
  (מילואים, חדש), ורק אז פורשים את הישן.

### למה החתימות ב-JSON ולא כקובץ `.sig`

זה התחיל כקובץ `.sig` נפרד, וזה לא שורד את הרשתות שהמוצר הזה חי בהן.
`raw.githubusercontent.com` מגיש `.sig` בתור `application/octet-stream`, ומסנני
תוכן עונים על זה בדף חסימה. נמדד על קו חי: `catalog.json` חזר 200 כ-`text/plain`
ו-`catalog.json.sig` חזר דף HTML של חסימה. המכשיר היה מאמת את הקטלוג מול פיסת
HTML, זורק אותו, ונשאר על העותק המוטמע לנצח - כשההודעה היחידה היא "החתימה אינה
תקינה".

`signatures.json` מוגש כטקסט ועובר. הוא גם בקשה אחת במקום שתיים. קבצי ה-`.sig`
עדיין מתפרסמים לצד, לאימות עם openssl.

**קובץ שהחתימה שלו לא מאמתת נזרק, והמכשיר נשאר על העותק הקודם.** אם גם הוא לא
קיים, נשאר העותק המוטמע ב-APK. כישלון סנכרון לעולם אינו פותח גישה.

### למה ECDSA ולא Ed25519

זה היה Ed25519, בהנחה המתועדת שהספק של המערכת תומך בו מ-API 33. הוא לא, לא על
חומרה אמיתית. נמדד על Samsung SM-A075F עם אנדרואיד 16 (API 36): כל מה שקיים
במכשיר בצורת Edwards הוא `AndroidKeyStore: KeyFactory/ED25519` - כלומר רק
ה-keystore, שנועד לייצר מפתחות בתוך חומרה מאובטחת ומסרב לייבא מפתח מבחוץ:

```
InvalidKeySpecException: To generate a key pair in Android Keystore, use
KeyPairGenerator initialized with KeyGenParameterSpec
```

התוצאה בשטח: כל מפתח מוצמד נדחה כפגום, כל הורדה דווחה כחתימה לא תקינה, והמכשיר
נשאר על הקטלוג המוטמע ב-APK בלי דרך להבדיל בין זה לבין זיוף.

ECDSA/P-256 קיים ב-AndroidOpenSSL בכל גרסה שהאפליקציה תומכת בה, הוא מה ש-openssl
מייצר עם `dgst -sha256 -sign`, ולא דורש שום תלות. הוא גם מבטל את רצפת ה-API 33
שהתכנון הקודם גרר, כך שגם מכשירים מתחת ל-Tiramisu מאמתים ומסתנכרנים.

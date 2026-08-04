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

catalog.json      catalog.json.sig     catalog.version    ← נבנים, לא נערכים ביד
policies.json     policies.json.sig                       ← נבנים, לא נערכים ביד
```

קובץ אחד לאפליקציה, מסודר לפי קטגוריה. זה מונע קונפליקטי merge ומאפשר PR ממוקד.
חמשת הקבצים שבשורש הם התוצר, והם היחידים שהאפליקציה מורידה.

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

## תהליך עדכון

1. ערוך או הוסף קובץ תחת `apps/` או `policies/`.
2. הרץ `./tools/release.sh` - הוא בונה, חותם ומאמת.
3. commit לחמשת קבצי התוצר יחד עם קובץ המקור, ודחוף ל-`main`.

תוך שש שעות לכל היותר כל מכשיר מושך את השינוי. אין צורך בגרסה חדשה של
האפליקציה.

ה-CI דוחה JSON לא תקין, קובץ בקטגוריה שגויה, `sha256` שאינו 64 תווי hex, תוצר
שלא תואם למקור, וחתימה שאינה מאמתת.

## בנייה וחתימה

```bash
./tools/release.sh [path/to/private-key.pem]     # ברירת מחדל ../keys/shani-shvilin-signing.pem
./tools/verify.sh                                # אימות בלבד, כמו שהמכשיר עושה
python tools/build_catalog.py --check            # התוצר תואם למקור?
python tools/build_policies.py --check
```

`catalog.version` הוא קובץ צד קטן שהאפליקציה מושכת לפני הקטלוג עצמו:

```json
{ "schemaVersion": 1, "entryCount": 13, "revision": "33f7b1e3c0b05884" }
```

ה-`revision` הוא טביעת אצבע של **הנתונים בלבד**, לא של הקובץ. בנייה חוזרת ללא
שינוי תוכן מייצרת את אותו revision, והמכשיר לא מוריד כלום.

## מפתחות

החתימה היא Ed25519, והאימות במכשיר הוא חובה - לא best effort.

- `keys/signing-current.pub.pem`, `keys/signing-standby.pub.pem` - החצאים
  הציבוריים, ו-`keys/public-keys.hex` הוא בדיוק מה שמוצמד באפליקציה
  ב-`SyncWorker.PINNED_PUBLIC_KEYS`.
- **המפתחות הפרטיים אינם בריפו הזה ואינם ב-GitHub.** החתימה רצה מקומית על
  המכונה שמחזיקה אותם; ה-CI רק מאמת, ולכן אין כאן secret שאפשר לגנוב.
- שני מפתחות מוצמדים, נוכחי ומילואים, כדי שאפשר יהיה להחליף מפתח בלי לנתק
  מכשירים שנשארו על גרסה ישנה: חותמים במפתח המילואים, משחררים גרסה שמצמידה
  (מילואים, חדש), ורק אז פורשים את הישן.

**קובץ שהחתימה שלו לא מאמתת נזרק, והמכשיר נשאר על העותק הקודם.** אם גם הוא לא
קיים, נשאר העותק המוטמע ב-APK. כישלון סנכרון לעולם אינו פותח גישה.

> אימות Ed25519 דרך ספק המערכת קיים מ-API 33. מתחת לזה הסנכרון מדווח
> `Unsupported` ונשאר על העותק המוטמע, ולא מקבל קובץ לא מאומת.

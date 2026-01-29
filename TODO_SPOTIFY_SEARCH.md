# TODO: Spotify плейлисты + Интерактивный поиск

## Статус: Ожидает Spotify Credentials

---

## 1. Плейлисты Spotify

### Как работает
```
Spotify API → "Track - Artist" → YouTube поиск → Воспроизведение
```

Spotify НЕ даёт аудио, только метаданные. Все боты (Rythm, Hydra, FredBoat) делают так:
1. Получают список треков из Spotify (название + исполнитель)
2. Ищут каждый трек на YouTube
3. Воспроизводят YouTube версию

### Нужно для реализации

**1. Зарегистрировать Spotify App:**
- https://developer.spotify.com/dashboard
- Создать приложение (бесплатно)
- Получить `CLIENT_ID` и `CLIENT_SECRET`

**2. Добавить в `.env`:**
```
SPOTIFY_CLIENT_ID=твой_client_id
SPOTIFY_CLIENT_SECRET=твой_client_secret
```

**3. Установить библиотеку:**
```bash
pip install spotipy
```

### Реализация (план)

**Файл:** `utils/spotify_utils.py`
```python
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Инициализация
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

# Получение треков из плейлиста
def get_playlist_tracks(playlist_url):
    playlist_id = extract_playlist_id(playlist_url)
    results = sp.playlist_tracks(playlist_id)

    tracks = []
    for item in results['items']:
        track = item['track']
        tracks.append({
            'name': track['name'],
            'artist': track['artists'][0]['name'],
            'search_query': f"{track['name']} {track['artists'][0]['name']}",
            'duration_ms': track['duration_ms'],
            'thumbnail': track['album']['images'][0]['url']
        })
    return tracks
```

**Команда:** `/play <spotify_playlist_url>`
- Определяет что это Spotify плейлист
- Получает все треки
- Добавляет в очередь с прогрессом: "Добавлено 15/50 треков..."

---

## 2. Интерактивный поиск

### Как работает
Пользователь вводит `/search metallica nothing else matters`

Бот показывает dropdown меню с 5 результатами:
```
1. Nothing Else Matters - Metallica (6:28)
2. Nothing Else Matters (Live) - Metallica (7:15)
3. Nothing Else Matters Cover - Someone (5:30)
...
```

Пользователь выбирает → трек добавляется в очередь.

### Реализация (план)

**Файл:** `commands/music/search.py`
```python
@app_commands.command(name="search", description="Поиск треков")
async def search(interaction: discord.Interaction, query: str):
    # Поиск 5 результатов через yt-dlp
    results = await search_youtube(f"ytsearch5:{query}")

    # Создаём Select Menu
    options = [
        discord.SelectOption(
            label=f"{r['title'][:50]}",
            description=f"{r['duration']} • {r['channel']}",
            value=r['url']
        )
        for r in results[:5]
    ]

    view = SearchResultsView(options)
    await interaction.response.send_message("Выберите трек:", view=view)
```

**View с Select Menu:**
```python
class SearchResultsView(discord.ui.View):
    @discord.ui.select(placeholder="Выберите трек...")
    async def select_track(self, interaction, select):
        url = select.values[0]
        # Добавляем в очередь
        await add_to_queue(url, interaction)
```

---

## 3. Дополнительные улучшения

### Поддержка разных Spotify ссылок
- `open.spotify.com/track/xxx` - один трек
- `open.spotify.com/playlist/xxx` - плейлист
- `open.spotify.com/album/xxx` - альбом
- `open.spotify.com/artist/xxx` - топ треки артиста

### Умный поиск YouTube
Для лучшего соответствия искать:
```
"{track_name}" "{artist}" official audio
```

### Лимиты и оптимизация
- Spotify API: 100 треков за запрос (пагинация для больших плейлистов)
- Параллельная обработка: добавлять треки пачками по 5-10
- Прогресс бар: показывать сколько добавлено

---

## Источники
- [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
- [Spotipy Documentation](https://spotipy.readthedocs.io/)
- [spotify-dlp](https://pypi.org/project/spotify-dlp/)
- [Discord Music Bots Guide](https://www.topmediai.com/ai-tips/discord-music-bots/)

---

## Когда готов
1. Добавь credentials в `.env`
2. Напиши Claude: "Реализуй Spotify плейлисты и интерактивный поиск"

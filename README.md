# PWiK Piaseczno iBOK - Интеграция для Home Assistant

<p align="center">
  <img src="images/logo.png" alt="PWiK Piaseczno Logo" width="300">
</p>

Интеграция Home Assistant для передачи показаний счетчиков воды и мониторинга водопотребления через личный кабинет **PWiK Piaseczno iBOK** (`https://ibok.pwikpiaseczno.pl/`).

---

## Возможности

- **Поддержка всех типов счетчиков**: автоматическое обнаружение как основного ввода (`N` — Główny), так и дополнительных подлинейников (`P` — Podlicznik / Сад).
- **Сенсоры для каждого счетчика**:
  - `sensor.wodomierz_<meter_id>_last_reading`: Последнее подтвержденное показание ($m^3$, `device_class: water`, `state_class: total_increasing`).
  - `sensor.wodomierz_<meter_id>_last_reading_date`: Дата последней фиксации показания.
  - `sensor.wodomierz_<meter_id>_submission_status`: Статус заявки (`allowed`, `pending`, `in_progress`, `rejected`, `approved`).
  - `sensor.wodomierz_<meter_id>_pending_reading`: Последнее поданное абонентом показание.
  - `sensor.wodomierz_<meter_id>_consumption_since_last_reading`: Реальный расход воды с момента последнего биллинга (рассчитывается в реальном времени при привязке к локальному импульсному или цифровому датчику в HA).
- **Кнопки управления**:
  - `button.wodomierz_<meter_id>_submit_reading`: Отправка текущих показаний из привязанного сенсора в один клик.
  - `button.wodomierz_<meter_id>_cancel_reading`: Отмена переданных показаний, если заявка находится в статусе ожидания (`pending`).
- **Службы автоматизации**:
  - `pwik.submit_reading`: Передача показаний счетчиков из автоматизаций (если параметры не указаны, автоматически считывает и отправляет показания для всех настроенных счетчиков).
  - `pwik.cancel_reading`: Отмена заявки на передачу показаний.
- **Интеллектуальная обработка сессий**: автоматическое обнаружение конфликтов одиночной сессии (`#loginWrongSessionLimit`) и аварийный сброс через `?logout=true&kill=true`.
- **Строгая валидация**:
  - Разделение целой и дробной части с учетом точной разрядности счетчика (`min_zakres`).
  - Проверка монотонного возрастания показания ($reading \ge last\_reading$).
  - Контроль ответов сервера через Base64-декодирование эндпоинта `?module=Errors`.

---

## Установка

### Способ 1: Установка через HACS (рекомендуется)
1. Откройте **HACS** в интерфейсе Home Assistant.
2. В правом верхнем углу нажмите меню с тремя точками и выберите **Пользовательские репозитории** (Custom repositories).
3. В поле репозитория укажите ссылку: `https://github.com/xpoh697/pwik`
4. В поле «Категория» выберите **Интеграция** (Integration) и нажмите **Добавить**.
5. Найдите интеграцию **PWiK Piaseczno iBOK**, нажмите **Скачать** и перезагрузите Home Assistant.

### Способ 2: Ручная установка
1. Скачайте архив репозитория или склонируйте его.
2. Скопируйте папку `custom_components/pwik` в директорию `config/custom_components/` вашего Home Assistant.
3. Перезагрузите Home Assistant.

---

## Настройка

1. В Home Assistant перейдите в **Настройки** -> **Устройства и службы** -> **Добавить интеграцию**.
2. Найдите **PWiK Piaseczno iBOK**.
3. Введите логин и пароль от личного кабинета iBOK.
4. На следующем шаге привяжите локальные датчики расхода воды Home Assistant (например, `sensor.lora_wmbus_bridge_apator_water_counter` для основного ввода и `sensor.podlicznik_value` для садового подлинейника).

---

## Использование в автоматизациях

### Пример регулярной отправки показаний (1-го числа месяца в 00:01 с отчетом в Telegram)

Интеграция автоматически считывает текущие значения из привязанных локальных сенсоров, нормализует единицы измерения и отправляет показания для всех счетчиков без необходимости повторно передавать значения в YAML:

```yaml
alias: "PWiK: Ежемесячная передача показаний воды"
description: "Автоматическая отправка показаний основного счетчика и подлинейника в PWiK Piaseczno 1-го числа каждого месяца в 00:01 с отчетом в Telegram"
triggers:
  - trigger: time
    at: "00:01:00"
conditions:
  - condition: template
    value_template: "{{ now().day == 1 }}"
actions:
  # Отправляем показания всех счетчиков из привязанных сенсоров
  - action: pwik.submit_reading
    data: {}
  - delay:
      seconds: 5
  - action: telegram_bot.send_message
    data:
      title: "💧 *PWiK Piaseczno: Показания воды переданы*"
      message: >
        ✅ *Показания счетчиков воды успешно переданы в личный кабинет!*

        🚰 *Основной счетчик (72130027):*
        • Показание: `{{ states('sensor.lora_wmbus_bridge_apator_water_counter') }} м³`

        🌿 *Подлинейник (240630342A):*
        • Показание: `{{ states('sensor.podlicznik_value') }} м³`

        📅 *Дата фиксации:* `{{ now().strftime('%Y-%m-%d %H:%M') }}`
        🏢 *Статус:* Заявка зарегистрирована
      message_thread_id: 49
mode: single
```

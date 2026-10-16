# PWiK Piaseczno iBOK - Интеграция для Home Assistant

<p align="center">
  <img src="images/logo.png" alt="PWiK Piaseczno Logo" width="300">
</p>

Интеграция Home Assistant для передачи показаний счетчиков воды и мониторинга водопотребления через личный кабинет **PWiK Piaseczno iBOK** (`https://ibok.pwikpiaseczno.pl/`).

---

## Возможности

- **Поддержка всех типов счетчиков**: автоматическое обнаружение как основного ввода (`N` — Główny), так и дополнительных подлинейников (`P` — Podlicznik / Сад).
- **Сенсоры для каждого счетчика**:
  - `sensor.<meter_id>_last_reading`: Последнее подтвержденное показание ($m^3$, `device_class: water`, `state_class: total_increasing`).
  - `sensor.<meter_id>_last_reading_date`: Дата последней фиксации показания.
  - `sensor.<meter_id>_reading_submission_status`: Статус заявки (`allowed`, `pending`, `in_progress`, `rejected`, `approved`).
  - `sensor.<meter_id>_pending_reading`: Текущее поданное значение, ожидающее подтверждения оператором.
  - `sensor.<meter_id>_consumption_since_last_reading`: Реальный расход воды с момента последнего биллинга (при привязке к локальному импульсному/цифровому датчику в HA).
- **Кнопки управления**:
  - `button.<meter_id>_submit_reading`: Отправка текущих показаний из привязанного сенсора в один клик.
  - `button.<meter_id>_cancel_reading`: Отмена переданных показаний, если заявка находится в статусе ожидания (`pending`).
- **Службы автоматизации**:
  - `pwik.submit_reading`: Передача показаний счетчика из автоматизаций (например, в конце расчетного периода).
  - `pwik.cancel_reading`: Отмена заявки на передачу показаний.
- **Интеллектуальная обработка сессий**: автоматическое обнаружение конфликтов одиночной сессии (`#loginWrongSessionLimit`) и аварийный сброс через `?logout=true&kill=true`.
- **Строгая валидация**:
  - Разделение целой и дробной части с учетом точной разрядности счетчика (`min_zakres`).
  - Проверка монотонного возрастания показания ($reading \ge last\_reading$).
  - Контроль ответов сервера через Base64-декодирование эндпоинта `?module=Errors`.

---

## Установка

### Вариант 1: Скрипт деплоя в HA (рекомендуется)
Выполните скрипт `deploy.ps1` для копирования файлов напрямую на ваш сервер Home Assistant:
```powershell
.\deploy.ps1
```

### Вариант 2: Вручную через Samba / SCP
Скопируйте папку `custom_components/pwik` в директорию `config/custom_components/` вашего Home Assistant.

После копирования перезагрузите Home Assistant.

---

## Настройка

1. В Home Assistant перейдите в **Настройки** -> **Устройства и службы** -> **Добавить интеграцию**.
2. Найдите **PWiK Piaseczno iBOK**.
3. Введите логин и пароль от личного кабинета iBOK.
4. На следующем шаге при желании привяжите локальные датчики расхода воды Home Assistant (например, `sensor.water_meter_total`) к обнаруженным счетчикам.

---

## Использование в автоматизациях

### Пример регулярной отправки показаний (раз в месяц)
```yaml
alias: "PWiK: Ежемесячная передача показаний воды"
trigger:
  - platform: time
    at: "10:00:00"
condition:
  - condition: template
    value_template: "{{ now().day == 28 }}"
action:
  - service: pwik.submit_reading
    data:
      meter_id: "72130027"
      value: "{{ states('sensor.water_meter_pulse_total') }}"
      comment: "Подано автоматически из Home Assistant"
```

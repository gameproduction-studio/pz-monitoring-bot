(() => {
  const EN = {
    overview:"Overview", bases:"Bases", vehicles:"Vehicles", food:"Food & liquids", resources:"Resources",
    history:"History", language:"Panel language", connecting:"Connecting…", online:"Live data connected",
    offline:"Local dashboard unavailable", liveLedger:"LIVE LEDGER // READ ONLY", lastInventory:"LAST INVENTORY",
    loading:"Reading the survivor ledger…", noData:"No data yet",
    takeInventoryHint:"Choose “Take inventory” in game; the data will appear here automatically.",
    titles:{overview:"Shelter summary",bases:"Registered bases",vehicles:"Registered vehicles",food:"Food & liquid stock",resources:"Resource ledger",history:"Change journal"},
    carrying:"Carrying", containers:"Containers", items:"Item instances", calories:"Edible calories",
    character:"Character", operational:"Operational picture", current:"live", stale:"last known",
    base:"Base", radius:"Radius", loaded:"Loaded now", lastKnown:"Last known", search:"Search by name or location…",
    name:"Name", quantity:"Qty", location:"Location", condition:"Condition", onCharacter:"Character",
    inBases:"Bases", inVehicles:"Vehicles", fuel:"Fuel", battery:"Battery", overall:"Overall",
    cargo:"Cargo containers", freshness:"Freshness", preservation:"Storage", caloriesShort:"kcal",
    edible:"Edible stock", disposal:"Compost / disposal", all:"All", duplicates:"Duplicates",
    snapshotUnavailable:"The snapshot is unavailable or parsing failed.", sequence:"Sequence", updated:"Updated",
    inventory:"Inventory", equipped:"equipped", coordinates:"Coordinates", state:"State", noAlerts:"No urgent warnings.",
    details:"Details", source:"Source", gameBuild:"Game build"
  };
  const RU = {
    overview:"Обзор", bases:"Базы", vehicles:"Автомобили", food:"Еда и жидкости", resources:"Ресурсы",
    history:"История", language:"Язык панели", connecting:"Подключение…", online:"Живые данные подключены",
    offline:"Локальная панель недоступна", liveLedger:"ЖИВАЯ ОПИСЬ // ТОЛЬКО ЧТЕНИЕ", lastInventory:"ПОСЛЕДНЯЯ ОПИСЬ",
    loading:"Читаю журнал выжившего…", noData:"Данных пока нет",
    takeInventoryHint:"В игре выберите «Сделать опись», затем данные появятся здесь автоматически.",
    titles:{overview:"Сводка убежища",bases:"Зарегистрированные базы",vehicles:"Закреплённые автомобили",food:"Запасы еды и жидкостей",resources:"Опись ресурсов",history:"Журнал изменений"},
    carrying:"Нагрузка", containers:"Контейнеры", items:"Экземпляры предметов", calories:"Съедобные калории",
    character:"Персонаж", operational:"Оперативная сводка", current:"актуально", stale:"последнее известное",
    base:"База", radius:"Радиус", loaded:"Загружено сейчас", lastKnown:"Последнее известное", search:"Поиск по названию или месту…",
    name:"Название", quantity:"Кол-во", location:"Где лежит", condition:"Состояние", onCharacter:"На персонаже",
    inBases:"На базах", inVehicles:"В авто", fuel:"Топливо", battery:"Аккумулятор", overall:"Общее состояние",
    cargo:"Грузовые отсеки", freshness:"Свежесть", preservation:"Хранение", caloriesShort:"ккал",
    edible:"Съедобный запас", disposal:"Компост / утилизация", all:"Все", duplicates:"Повторы",
    snapshotUnavailable:"Снимок недоступен или его разбор завершился ошибкой.", sequence:"Номер снимка", updated:"Обновлено",
    inventory:"Инвентарь", equipped:"экипировано", coordinates:"Координаты", state:"Состояние", noAlerts:"Срочных предупреждений нет.",
    details:"Подробнее", source:"Источник", gameBuild:"Версия игры"
  };
  const NAV = {
    AR:["نظرة عامة","القواعد","المركبات","الطعام والسوائل","الموارد","السجل"],
    CA:["Resum","Bases","Vehicles","Menjar i líquids","Recursos","Historial"],
    CH:["總覽","基地","車輛","食物與液體","資源","歷史"],
    CN:["概览","基地","车辆","食物与液体","资源","历史"],
    CS:["Přehled","Základny","Vozidla","Jídlo a tekutiny","Zdroje","Historie"],
    DA:["Overblik","Baser","Køretøjer","Mad og væsker","Ressourcer","Historik"],
    DE:["Übersicht","Basen","Fahrzeuge","Nahrung & Flüssigkeit","Ressourcen","Verlauf"],
    ES:["Resumen","Bases","Vehículos","Comida y líquidos","Recursos","Historial"],
    ES_CL:["Resumen","Bases","Vehículos","Comida y líquidos","Recursos","Historial"],
    ES_MX:["Resumen","Bases","Vehículos","Comida y líquidos","Recursos","Historial"],
    FI:["Yleiskatsaus","Tukikohdat","Ajoneuvot","Ruoka ja nesteet","Resurssit","Historia"],
    FR:["Vue d’ensemble","Bases","Véhicules","Nourriture et liquides","Ressources","Historique"],
    HU:["Áttekintés","Bázisok","Járművek","Étel és folyadék","Készletek","Előzmények"],
    ID:["Ringkasan","Markas","Kendaraan","Makanan & cairan","Sumber daya","Riwayat"],
    IT:["Panoramica","Basi","Veicoli","Cibo e liquidi","Risorse","Cronologia"],
    JP:["概要","拠点","車両","食料と液体","資源","履歴"],
    KO:["개요","기지","차량","음식 및 액체","자원","기록"],
    NL:["Overzicht","Basissen","Voertuigen","Voedsel en vloeistoffen","Voorraden","Geschiedenis"],
    NO:["Oversikt","Baser","Kjøretøy","Mat og væske","Ressurser","Historikk"],
    PL:["Przegląd","Bazy","Pojazdy","Żywność i płyny","Zasoby","Historia"],
    PT:["Visão geral","Bases","Veículos","Comida e líquidos","Recursos","Histórico"],
    PTBR:["Visão geral","Bases","Veículos","Comida e líquidos","Recursos","Histórico"],
    RO:["Prezentare","Baze","Vehicule","Hrană și lichide","Resurse","Istoric"],
    STREW:["Overview","Bases","Vehicles","Food & liquids","Resources","History"],
    TH:["ภาพรวม","ฐาน","ยานพาหนะ","อาหารและของเหลว","ทรัพยากร","ประวัติ"],
    TR:["Genel bakış","Üsler","Araçlar","Yiyecek ve sıvılar","Kaynaklar","Geçmiş"],
    UA:["Огляд","Бази","Автомобілі","Їжа та рідини","Ресурси","Історія"]
  };
  const CATALOG = {EN, RU};
  Object.entries(NAV).forEach(([code, labels]) => {
    CATALOG[code] = Object.assign({}, EN, {
      overview:labels[0], bases:labels[1], vehicles:labels[2],
      food:labels[3], resources:labels[4], history:labels[5]
    });
  });
  window.PZ_I18N = {catalog:CATALOG, fallback:EN};
})();

"""Тесты парсеров атрибутов (TDD). Запуск: pytest -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freedom_parser.common import attributes as A


class TestTireSize:
    def test_standard_with_indices(self):
        r = A.parse_tire_size("195/65 R16 91V")
        assert r["tire_width"] == 195
        assert r["tire_profile"] == 65
        assert r["tire_diameter"] == 16
        assert r["load_index"] == "91"
        assert r["speed_index"] == "V"

    def test_no_space_before_r(self):
        r = A.parse_tire_size("205/55R16 91W")
        assert r["tire_width"] == 205
        assert r["tire_profile"] == 55
        assert r["tire_diameter"] == 16
        assert r["speed_index"] == "W"

    def test_inside_full_name(self):
        r = A.parse_tire_size("Bridgestone Turanza T005 175/65 R14 82T")
        assert r["tire_width"] == 175
        assert r["tire_profile"] == 65
        assert r["tire_diameter"] == 14
        assert r["load_index"] == "82"
        assert r["speed_index"] == "T"

    def test_truck_float_diameter(self):
        r = A.parse_tire_size("385/65 R22.5 160K")
        assert r["tire_width"] == 385
        assert r["tire_profile"] == 65
        assert r["tire_diameter"] == 22.5

    def test_no_indices(self):
        r = A.parse_tire_size("Cordiant Sport 2 205/55 R16")
        assert r["tire_width"] == 205
        assert r["tire_profile"] == 55
        assert r["tire_diameter"] == 16
        assert r["load_index"] == ""
        assert r["speed_index"] == ""

    def test_no_size_returns_empty(self):
        r = A.parse_tire_size("Какое-то масло без размера")
        assert r["tire_width"] is None
        assert r["tire_diameter"] is None


class TestPitstopSlug:
    def test_full_slug(self):
        r = A.tire_size_from_pitstop_slug("175-65-14-82-t--")
        assert r["tire_width"] == 175
        assert r["tire_profile"] == 65
        assert r["tire_diameter"] == 14
        assert r["load_index"] == "82"
        assert r["speed_index"] == "T"

    def test_full_url(self):
        r = A.tire_size_from_pitstop_slug(
            "/catalog/tyre/pirelli/cinturato-p7/205-55-16-91-w--/")
        assert r["tire_width"] == 205
        assert r["tire_diameter"] == 16
        assert r["speed_index"] == "W"

    def test_garbage(self):
        assert A.tire_size_from_pitstop_slug("turanza-t005")["tire_width"] is None


class TestSeason:
    def test_winter(self):
        assert A.detect_season("Зимняя шина с шипами") == "Зимняя"
        assert A.detect_season("Nokian Hakkapeliitta winter") == "Зимняя"

    def test_summer(self):
        assert A.detect_season("Летние шины Triangle") == "Летняя"
        assert A.detect_season("Summer tyre") == "Летняя"

    def test_all_season(self):
        assert A.detect_season("Всесезонная резина") == "Всесезонная"
        assert A.detect_season("All season tire") == "Всесезонная"

    def test_translit_slug(self):
        # сезон из транслит-slug категории car-city
        assert A.detect_season("siny-letnie") == "Летняя"
        assert A.detect_season("siny-zimnie") == "Зимняя"

    def test_unknown(self):
        assert A.detect_season("Bridgestone Turanza T005") == ""


class TestRunflat:
    def test_runflat_variants(self):
        assert A.detect_runflat("Pirelli Cinturato P7 RunFlat") is True
        assert A.detect_runflat("Continental 205/55 R16 RFT") is True
        assert A.detect_runflat("Bridgestone 225/45 R17 ROF") is True

    def test_not_runflat(self):
        assert A.detect_runflat("Bridgestone Turanza T005 175/65 R14") is False
        # "zp" внутри слова не должно ложно срабатывать
        assert A.detect_runflat("Какой-то bzpzp товар") is False


class TestStudded:
    def test_studded_true(self):
        assert A.parse_studded("Cordiant Snow Cross 185/65 R15 с шипами") is True
        assert A.parse_studded("Шипованная зимняя 205/55 R16") is True

    def test_studded_false(self):
        assert A.parse_studded("Yokohama Ice Guard IG60 без шипов") is False
        assert A.parse_studded("Nokian Hakka 205/55 R16 липучка") is False

    def test_studded_unknown(self):
        assert A.parse_studded("Triangle TC 101 215/55 R16 97W") is None

    def test_extract_for_group_includes_studded(self):
        a = A.extract_for_group("tires", "Cordiant Snow Cross 185/65 R15 с шипами", "")
        assert a["studded"] is True

    def test_summer_tire_studded_false(self):
        # летняя шина без упоминания шипов -> заведомо нешипованная
        a = A.extract_for_group("tires", "Triangle TC 101 215/55 R16 97W", "siny-letnie")
        assert a["season"] == "Летняя"
        assert a["studded"] is False

    def test_winter_unmentioned_studded_unknown(self):
        a = A.extract_for_group("tires", "Pirelli Winter SottoZero 205/55 R16", "")
        assert a["season"] == "Зимняя"
        assert a["studded"] is None


class TestViscosity:
    def test_dash(self):
        assert A.parse_viscosity("Castrol EDGE 5W-30 4L") == "5W-30"

    def test_no_dash_normalized(self):
        assert A.parse_viscosity("Mobil 1 5W30 синтетическое") == "5W-30"
        assert A.parse_viscosity("0W20") == "0W-20"

    def test_monograde(self):
        assert A.parse_viscosity("MANNOL M.O. SAE 30 API CD 3103") == "SAE 30"
        assert A.parse_viscosity("MANNOL M.O. SAE 20W API CD") == "SAE 20W"

    def test_none(self):
        assert A.parse_viscosity("Воздушный фильтр Mann") == ""
        assert A.parse_viscosity("ATF Dexron III") == ""


class TestVolume:
    def test_liters(self):
        assert A.parse_volume_liters("Castrol EDGE 5W-30 4 л") == 4.0
        assert A.parse_volume_liters("масло моторное, 1л") == 1.0
        assert A.parse_volume_liters("Shell Helix 4L") == 4.0

    def test_comma_decimal(self):
        assert A.parse_volume_liters("ATF 0,5 л") == 0.5

    def test_milliliters_to_liters(self):
        assert A.parse_volume_liters("Присадка 200 мл") == 0.2

    def test_none(self):
        assert A.parse_volume_liters("Фильтр масляный") is None


class TestOilType:
    def test_synthetic(self):
        assert A.detect_oil_type("Castrol EDGE синтетическое 5W-30") == "Синтетическое"
        assert A.detect_oil_type("Fully synthetic oil") == "Синтетическое"

    def test_semi_synthetic(self):
        assert A.detect_oil_type("Масло полусинтетическое 10W-40") == "Полусинтетическое"
        assert A.detect_oil_type("Semi-synthetic 10W40") == "Полусинтетическое"

    def test_mineral(self):
        assert A.detect_oil_type("Минеральное масло 15W-40") == "Минеральное"

    def test_hydrocracking(self):
        assert A.detect_oil_type("Моторное масло гидрокрекинговое FANFARO 5W-40") == "Гидрокрекинговое"

    def test_unknown(self):
        assert A.detect_oil_type("Castrol 5W-30") == ""


class TestBattery:
    def test_capacity(self):
        assert A.parse_capacity_ah("Аккумулятор 60 Ач 12V обратная") == 60
        assert A.parse_capacity_ah("AKB 75Ah") == 75

    def test_voltage(self):
        assert A.parse_voltage_v("60 Ач 12В обратная") == 12
        assert A.parse_voltage_v("грузовой 24 V") == 24
        assert A.parse_voltage_v("без напряжения") is None

    def test_polarity(self):
        assert A.detect_battery_polarity("60 Ач обратная полярность") == "Обратная"
        assert A.detect_battery_polarity("прямая полярность") == "Прямая"
        assert A.detect_battery_polarity("нет данных") == ""


class TestFilterType:
    def test_types(self):
        assert A.detect_filter_type("Масляный фильтр Mann") == "Масляный"
        assert A.detect_filter_type("Воздушные фильтры") == "Воздушный"
        assert A.detect_filter_type("Топливный фильтр") == "Топливный"
        assert A.detect_filter_type("Салонный фильтр угольный") == "Салонный"

    def test_unknown(self):
        assert A.detect_filter_type("Просто фильтр") == ""


class TestExtractForGroup:
    def test_winter_name_overrides_summer_category(self):
        # В категории siny-letnie встречаются зимние модели — имя важнее slug.
        a = A.extract_for_group("tires", "Yokohama Ice Guard IG60 215/55 R17 94Q", "siny-letnie")
        assert a["season"] == "Зимняя"
        a2 = A.extract_for_group("tires", "Cordiant Snow Cross 185/65 R15 с шипами", "siny-letnie")
        assert a2["season"] == "Зимняя"

    def test_category_fallback_when_name_silent(self):
        a = A.extract_for_group("tires", "Triangle TC 101 215/55 R16 97W", "siny-letnie")
        assert a["season"] == "Летняя"


class TestCarcityAvailability:
    def test_in_stock_zero_days(self):
        assert A.carcity_availability("…Предзаказ: +0 дней…") == "В наличии"

    def test_preorder_days(self):
        assert A.carcity_availability("Предзаказ: +3 дн") == "Под заказ: 3 дн"

    def test_best_across_sellers(self):
        assert A.carcity_availability("Предзаказ: +5 дней … Предзаказ: +0 дней") == "В наличии"

    def test_no_field_default(self):
        assert A.carcity_availability("нет поля") == "В наличии"


class TestCarcityChars:
    # chars теперь много-значный словарь: {имя -> [значения]}
    def test_battery(self):
        chars = {
            "Емкость": ["75.0 Ач"], "Напряжение": ["12 В"], "Полярность": ["прямая"],
            "Пусковой ток": ["650.0 А"], "Тип": ["свинцово-кислотный"],
            "Длина": ["260.0 мм"], "Ширина": ["173.0 мм"], "Высота": ["220.0 мм"],
            "Тип корпуса": ["европейский"], "Назначение": ["для легковых автомобилей"],
        }
        a = A.attributes_from_carcity_chars("batteries", chars)
        assert a["capacity_ah"] == 75
        assert a["voltage_v"] == 12
        assert a["start_current_a"] == 650
        assert a["polarity"] == "Прямая"
        assert a["battery_type"] == "свинцово-кислотный"
        assert a["case_type"] == "европейский"
        assert a["purpose"] == "для легковых автомобилей"
        assert "мм" in a["dimensions"]

    def test_oil(self):
        chars = {"Вид масла": ["минеральное"], "Класс вязкости SAE": ["10W-40"],
                 "Тип двигателя": ["двухтактный"], "Допуски": ["API TC"],
                 "Стандарт ATF": ["Dexron III"]}
        a = A.attributes_from_carcity_chars("oils", chars)
        assert a["oil_type"] == "Минеральное"
        assert a["viscosity"] == "10W-40"
        assert a["engine_type"] == "двухтактный"
        assert a["specification"] == "API TC"
        assert a["atf_standard"] == "Dexron III"

    def test_tire_season_and_extras(self):
        chars = {"Сезонность": ["зимние"], "Шипы": ["без шипов"],
                 "Ширина профиля": ["215"], "Высота профиля": ["55"],
                 "Диаметр диска": ["16"], "Название модели": ["TC101"],
                 "Тип шины": ["легковая"]}
        a = A.attributes_from_carcity_chars("tires", chars)
        assert a["season"] == "Зимняя"
        assert a["studded"] is False
        assert a["tire_width"] == 215
        assert a["model_name"] == "TC101"
        assert a["tire_type"] == "легковая"

    def test_multivalue_compat_years(self):
        chars = {"Год выпуска автомобиля": ["1997", "1998", "1999"]}
        a = A.attributes_from_carcity_chars("filters", chars)
        assert a["compatible_years"] == "1997; 1998; 1999"  # хвост сохранён

    def test_oem_numbers(self):
        chars = {"Запчасть совместима с ОЕМ": ["070115562"], "Номер OEM": ["26300-35505"]}
        assert A.carcity_oem_numbers(chars) == ["070115562", "26300-35505"]

    def test_empty_chars_skipped(self):
        a = A.attributes_from_carcity_chars("oils", {"Класс вязкости SAE": ["отсутствует"]})
        assert "viscosity" not in a


class TestPriceParse:
    def test_spaced_kzt(self):
        assert A.parse_price("9 506 ₸") == 9506.0
        assert A.parse_price("59860 т.") == 59860.0
        assert A.parse_price("1 180 000 тг") == 1180000.0

    def test_empty(self):
        assert A.parse_price("под заказ") is None
        assert A.parse_price("") is None

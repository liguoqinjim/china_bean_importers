import re
import sys
import typing


card_tail_pattern = re.compile(r".*银行.*\(([0-9]{4})\)")
common_date_pattern = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})")

# a map from currency name(chinese) to currency code(ISO 4217)
currency_code_map = {
    "人民币": "CNY",
    "港币": "HKD",
    "澳门元": "MOP",
    "美元": "USD",
    "日元": "JPY",
    "韩元": "KRW",
    "欧元": "EUR",
    "英镑": "GBP",
    "加拿大元": "CAD",
    "澳大利亚元": "AUD",
    "新加坡元": "SGD",
    "CNY": "CNY", # 兼容招商
}

SAME_AS_NARRATION = object()


class BillDetailMapping(typing.NamedTuple):
    # used to match an item's narration
    narration_keywords: typing.Optional[list[str]] = None
    # used to match an item's payee
    payee_keywords: typing.Optional[list[str]] = None
    # destination account (None means not specified)
    destination_account: typing.Optional[str] = None
    # tags to append in bill item
    additional_tags: typing.Optional[list[str]] = None
    # other metadata to append in bill
    additional_metadata: typing.Optional[dict[str, object]] = None

    def canonicalize(self):
        tags = set(self.additional_tags) if self.additional_tags else set()
        metadata = self.additional_metadata.copy() if self.additional_metadata else {}
        return self.destination_account, metadata, tags

    def match(
        self, desc: str, payee: str
    ) -> tuple[typing.Optional[str], dict[str, object], set[str]]:
        # LI
        if self.narration_keywords is not None and self.payee_keywords is not None:
            if len(self.narration_keywords) == 1 and len(self.payee_keywords) == 1:
                # print(f"liguoqinjim1:[{self.narration_keywords[0]}],[{self.payee_keywords[0]}],[{desc}],[{payee}]")
                if self.narration_keywords[0] in desc and self.payee_keywords[0] in payee:
                    # print("liguoqinjim2: 信用卡",desc,payee)
                    return self.canonicalize()
                else:
                    return None, {}, set()

        # match narration first
        if desc is not None and self.narration_keywords is not None:
            for keyword in self.narration_keywords:
                if keyword in desc:
                    return self.canonicalize()
        # then try payee
        if payee is not None and self.payee_keywords is not None:
            keywords = (
                self.narration_keywords
                if self.payee_keywords is SAME_AS_NARRATION
                else self.payee_keywords
            )
            for keyword in keywords:
                if keyword in payee:
                    return self.canonicalize()
        return None, {}, set()


def match_card_tail(src):
    assert type(src) == str
    m = card_tail_pattern.match(src)
    return m[1] if m else None


def open_pdf(config, name):
    import fitz

    doc = fitz.open(name)
    if doc.is_encrypted:
        for password in config["pdf_passwords"]:
            doc.authenticate(password)
            if not doc.is_encrypted:
                return doc
        if doc.is_encrypted:
            return None
    return doc


def find_account_by_card_number(config, card_number):
    if isinstance(card_number, int):
        card_number = str(card_number)
    # print("liguoqinjim3:",config["card_accounts"].items())
    for prefix, accounts in config["card_accounts"].items():
        # print("liguoqinjim4:",accounts,card_number)
        for bank, numbers in accounts.items():
            if card_number in numbers:
                # print("liguoqinjim find_account_by_card_number:", prefix, bank, card_number,numbers)
                return f"{prefix}:{bank}:{card_number}"
            else:
                if len(numbers) == 1 and card_number.endswith(numbers[0]):
                    # print("liguoqinjim find_account_by_card_number2:", prefix, bank, card_number,numbers)
                    return f"{prefix}:{bank}:{numbers[0]}"
                    

    return None


def match_destination_and_metadata(config, desc, payee):
    account = None
    mapping = None
    metadata = {}
    tags = set()

    # merge all possible results
    for m in config["detail_mappings"]:
        _mapping: BillDetailMapping = m
        new_account, new_metadata, new_tags = _mapping.match(desc, payee)
        # check compatibility
        if account is None:
            account, mapping = new_account, m
        elif new_account is not None:
            if new_account.startswith(account):
                # new account is deeper than or equal to current account
                account, mapping = new_account, m
            elif not account.startswith(new_account):
                my_warn(
                    f"""Conflict destination accounts found for narration {desc} and payee {payee}:
Old account {account} from {mapping}
New account {new_account} from {m}

""",
                    0,
                    "",
                )

        metadata.update(new_metadata)
        tags.update(new_tags)

    return account, metadata, tags


def match_currency_code(currency_name):
    return (
        currency_code_map[currency_name] if currency_name in currency_code_map else None
    )


def unknown_account(config, expense) -> str:
    return (
        config["unknown_expense_account"]
        if expense
        else config["unknown_income_account"]
    )


def in_blacklist(config, narration):
    for b in config["importers"]["card_narration_whitelist"]:
        if b in narration:
            return False
    for b in config["importers"]["card_narration_blacklist"]:
        if b in narration:
            return True
    return False


def my_assert(cond, msg, lineno, row):
    assert cond, f"{msg} on line {lineno}:\n{row}"


def my_warn(msg, lineno, row):
    print(f"WARNING: {msg} on line {lineno}:\n{row}\n", file=sys.stderr)

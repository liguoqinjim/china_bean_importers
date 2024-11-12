from dateutil.parser import parse
from beancount.core import data, amount
from beancount.core.number import D
import re

from china_bean_importers.common import *
from china_bean_importers.importer import PdfImporter

PAYEE_RE = re.compile(r"(\D*)(\d+)")


def gen_txn(config, file, parts, lineno, flag, card_acc, real_name):
    # Customer Type can be empty
    # assert len(parts) == 6 or len(parts) == 7
    my_assert(len(parts) == 5 or len(parts) == 6 or len(parts) == 7, f"Cannot parse line in PDF", lineno, parts) 
    if len(parts) == 5:
        parts += ['']

    # parts[5]: 对手信息
    payee = parts[5]
    if len(parts) == 7:
        # parts[6]: 客户摘要
        narration = parts[6]
    else:
        # parts[4]: 交易摘要
        narration = parts[4]
    # parts[0]: 记账日期
    date = parse(parts[0]).date()
    # parts[2]: 金额
    units1 = amount.Amount(D(parts[2]), "CNY")
    # parts[3]: 余额
    balance = amount.Amount(D(parts[3]), "CNY")
    # parts[2]: 币别
    currency_code = match_currency_code(parts[1])
    # print(f"liguoqinjim0: {date} {narration} [{units1}],[{parts[1]}]", file=sys.stderr, end=" -- ")

    # if in_blacklist(config, narration):
    #     print(
    #         f"Item in blacklist: {date} {narration} [{units1}]",
    #         file=sys.stderr,
    #         end=" -- ",
    #     )
    #     if units1 < amount.Amount(D(0), currency_code):
    #         print(f"Expense skipped", file=sys.stderr)
    #         return None
    #     else:
    #         print(f"Income kept in record", file=sys.stderr)

    metadata = data.new_metadata(file.name, lineno)
    metadata["balance"] = str(balance)
    tags = set()

    payee_account = None
    if m := PAYEE_RE.match(payee):
        payee, payee_account = m.groups()
    if payee_account:
        metadata["payee_account"] = payee_account
    metadata['input_source'] = "cmb_debit_card"

    if m := match_destination_and_metadata(config, narration, payee):
        (account2, new_meta, new_tags) = m
        metadata.update(new_meta)
        tags = tags.union(new_tags)
    if account2 is None:
        account2 = unknown_account(config, True)

    # Handle transfer to credit/debit cards
    # parts[5]: 对手信息
    # print("liguoqinjim0:",parts)
    # print(f"liguoqinjim1:[{real_name}],[{payee_account}],[{payee}]",parts)
    if payee.startswith(real_name) and payee_account:
        # print("liguoqinjim2:",payee_account)
        new_account = find_account_by_card_number(config, payee_account)
        if new_account is not None:
            account2 = new_account

    txn = data.Transaction(
        meta=metadata,
        date=date,
        flag=flag,
        payee=payee,
        narration=narration,
        tags=tags,
        links=data.EMPTY_SET,
        postings=[
            data.Posting(
                account=card_acc,
                units=units1,
                cost=None,
                price=None,
                flag=None,
                meta=None,
            ),
            data.Posting(
                account=account2,
                units=None,
                cost=None,
                price=None,
                flag=None,
                meta=None,
            ),
        ],
    )
    return txn


class Importer(PdfImporter):
    def __init__(self, config) -> None:
        import re

        super().__init__(config)
        self.match_keywords = ["招商银行交易流水"]
        self.file_account_name = "cmbc_debit_card"
        self.column_offsets = [30, 50, 100, 200, 280, 350, 400]
        self.content_start_keyword = "Party"  # "Counter Party"
        self.content_end_regex = re.compile(
            r"^\d+/\d+$"
        )  # match page number like "1/5"
        self.content_end_keyword = "————"  # match last page

    def parse_metadata(self, file):
        match = re.search(r"名：(\w+)", self.full_content)
        assert match
        self.real_name = match[1]

        match = re.search(r"[0-9]{16}", self.full_content)
        assert match
        card_number = match[0]
        self.card_acc = find_account_by_card_number(self.config, card_number[-4:])
        my_assert(self.card_acc, f"Unknown card number {card_number}", 0, 0)

    def generate_tx(self, row, lineno, file):
        return gen_txn(
            self.config, file, row, lineno, self.FLAG, self.card_acc, self.real_name
        )

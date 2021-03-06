#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
__author__ = 'CodeFace'
"""
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5.QtGui import *
from .util import ButtonsLineEdit, Buttons, CancelButton, MessageBoxMixin
from .amountedit import AmountEdit
from electrum.bitcoin import b58_address_to_hash160, hash160_to_b58_address, is_hash160, Delegation, bfh, bh2u
from electrum import constants
from electrum.i18n import _
from electrum.plugins.trezor.trezor import TrezorKeyStore
from electrum.bitcoin import Delegation


class DelegationLayout(QGridLayout):
    def __init__(self, dialog, dele: 'Delegation', mode: str):
        """
        :type dialog: QDialog
        :type callback: func
        """
        QGridLayout.__init__(self)
        self.setSpacing(8)
        self.setColumnStretch(3, 1)
        self.dialog = dialog
        self.dele = dele
        self.mode = mode

        if isinstance(self.dialog.parent().wallet.keystore, TrezorKeyStore):
            self.dialog.show_message('Trezor does not support staking delegation for now')
            self.dialog.reject()
            return

        if dele and dele.addr:
            self.addresses = [dele.addr]
        else:
            self.addresses = ['']
            for addr in self.dialog.parent().wallet.get_addresses_sort_by_balance():
                if addr in self.dialog.parent().wallet.db.list_delegations():
                    continue
                addr_type, __ = b58_address_to_hash160(addr)
                if addr_type == constants.net.ADDRTYPE_P2PKH:
                    self.addresses.append(addr)

        address_lb = QLabel(_("Address:"))
        self.address_combo = QComboBox()
        self.address_combo.setMinimumWidth(300)
        self.address_combo.addItems(self.addresses)
        self.addWidget(address_lb, 1, 0)
        self.addWidget(self.address_combo, 1, 1, 1, -1)
        self.address_combo.currentIndexChanged.connect(self.on_address)

        staker_lb = QLabel(_("Staker:"))
        self.staker_e = ButtonsLineEdit()
        self.addWidget(staker_lb, 2, 0)
        self.addWidget(self.staker_e, 2, 1, 1, -1)

        fee_lb = QLabel(_('Fee Percent:'))
        self.fee_e = QLineEdit()
        self.addWidget(fee_lb, 3, 0)
        self.addWidget(self.fee_e, 3, 1, 1, -1)

        self.optional_lb = QLabel(_('Optional:'))
        self.addWidget(self.optional_lb, 4, 0)
        self.optional_widget = QWidget()
        optional_layout = QHBoxLayout()
        optional_layout.setContentsMargins(0, 0, 0, 0)
        optional_layout.setSpacing(0)
        gas_limit_lb = QLabel(_('gas limit: '))
        self.gas_limit_e = AmountEdit(lambda: '', True, None, 0, 0)
        self.gas_limit_e.setText('2250000')
        gas_price_lb = QLabel(_('gas price: '))
        self.gas_price_e = AmountEdit(lambda: '', False, None, 8, 0)
        self.gas_price_e.setText('0.00000040')
        optional_layout.addWidget(gas_limit_lb)
        optional_layout.addWidget(self.gas_limit_e)
        optional_layout.addStretch(1)
        optional_layout.addWidget(gas_price_lb)
        optional_layout.addWidget(self.gas_price_e)
        optional_layout.addStretch(0)
        self.optional_widget.setLayout(optional_layout)
        self.addWidget(self.optional_widget, 4, 1, 1, -1)

        self.cancel_btn = CancelButton(dialog)
        self.do_btn = QPushButton(self.mode[0].upper() + self.mode[1:])
        self.do_btn.clicked.connect(self.do)

        buttons = Buttons(*[self.cancel_btn, self.do_btn])
        buttons.addStretch()
        self.addLayout(buttons, 5, 2, 2, -1)
        self.update()

    def update(self):
        super().update()
        self.staker_e.setReadOnly(False)
        self.fee_e.setReadOnly(False)
        self.staker_e.setText('')
        self.fee_e.setText('')

        dele_exist = self.dele and self.dele.staker and self.dele.fee
        if dele_exist:
            self.staker_e.setText(self.dele.staker)
            self.fee_e.setText(str(self.dele.fee))

        dele_readonly = self.mode == 'undelegate' or (self.mode == 'add' and dele_exist)
        if dele_readonly:
            self.staker_e.setReadOnly(True)
            self.fee_e.setReadOnly(True)

        can_edit_gas = self.mode in ['undelegate', 'edit'] or (self.mode == 'add' and not dele_exist)
        if can_edit_gas:
            # add e existed delegation
            self.optional_lb.setHidden(False)
            self.optional_widget.setHidden(False)
        else:
            # create a new delegation or update a existed delegation
            self.optional_lb.setHidden(True)
            self.optional_widget.setHidden(True)

    def on_address(self, i):
        addr = self.addresses[i]
        if self.mode == 'add':
            self.dele = None
        if len(addr) > 0:
            try:
                r = self.dialog.parent().network.run_from_another_thread(self.dialog.parent().network.request_delegation_info(addr))
                if r:
                    if r[0] != '0x0000000000000000000000000000000000000000':
                        staker = hash160_to_b58_address(bfh(r[0][2:]), constants.net.ADDRTYPE_P2PKH)
                        self.dele = Delegation(addr=addr, staker=staker, fee=r[1])
            except BaseException as e:
                import traceback, sys
                traceback.print_exc(file=sys.stderr)
                # self.dialog.show_message(str(e))
        self.update()

    def parse_values(self):
        def parse_edit_value(edit, times=10 ** 8):
            return int(edit.get_amount() * times)
        return parse_edit_value(self.gas_limit_e, 1), parse_edit_value(self.gas_price_e)

    def do(self):
        try:
            staker = self.staker_e.text()
            if not is_hash160(staker):
                addr_type, staker = b58_address_to_hash160(staker)
                if addr_type != constants.net.ADDRTYPE_P2PKH:
                    raise Exception('wrong staker address')
                staker = bh2u(staker)

            fee = int(self.fee_e.text())
            if fee < 0 or fee > 99:
                raise Exception('fee should between 0 and 99')

            addr = self.addresses[self.address_combo.currentIndex()]
            if not addr:
                raise Exception('please select a address')

            gas_limit, gas_price = self.parse_values()
            if gas_limit < 2250000:
                raise Exception('a minimum of 2,250,000 gas_limit is required')

            dele_exist = self.dele and self.dele.staker and self.dele.fee

            if self.mode == 'add' and dele_exist:
                self.dialog.parent().set_delegation(self.dele)
            elif self.mode in ['edit', 'add']:
                if dele_exist and self.staker_e.text() == self.dele.staker and fee == self.dele.fee:
                    return
                self.dialog.parent().call_add_delegation(addr, staker, fee, gas_limit, gas_price, self.dialog)
            elif self.mode == 'undelegate':
                self.dialog.parent().call_remove_delegation(addr, gas_limit, gas_price, self.dialog)

            self.dialog.reject()

        except (BaseException,) as e:
            import traceback, sys
            traceback.print_exc(file=sys.stderr)
            self.dialog.show_message(str(e))


class DelegationDialog(QDialog, MessageBoxMixin):

    def __init__(self, parent, dele: 'Delegation', mode: str):
        """
        :type parent: ElectrumWindow
        :type token: Token
        """
        QDialog.__init__(self, parent=parent)
        self.setMinimumSize(500, 100)
        self.setWindowTitle(_('Stake Delegation'))
        self.dele = dele
        layout = DelegationLayout(self, dele=dele, mode=mode)
        self.setLayout(layout)


import sys
import time
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox
from PyQt5 import QtWidgets
from PyQt5.Qt import QThread, pyqtSignal
from UI import Ui_MainWindow, plot_window, plot_collector
from adc_collect import collect_data
from envelope_process import envelope
from classifier import one_class_svm
import numpy as np
from variance import window_var
from patternmatch import pattern_match
import threading
from modify_features import *
import serial
import serial.tools.list_ports
from encrypt import encrypt
import matplotlib.pyplot as plt
import matlab.engine
eng = matlab.engine.start_matlab()


def get_features(collector: collect_data):
    while True:
        filtered_data = collector.start(m_time=13)
        upper, _ = envelope(filtered_data, 100).start()
        upper = upper[int(2302 * 1):-int(2302 * 0.5)]
        upper = upper.reshape(-1)
        upper = matlab.double(initializer=list(upper), size=(1, len(upper)), is_complex=False)
        upper = eng.smoothdata(upper, 'gaussian', 400, nargout=1)
        upper = upper[0]
        var_upper = np.array(upper).astype(float)
        rhythm_number = collector.get_rhythm_number(enveloped_data=var_upper)
        end_points, _ = window_var(data=var_upper, head=rhythm_number).start()
        end_points = np.sort(end_points)
        end_points = end_points[1::2]
        start_points, data_time, data_seg, _time = eng.patterMatch(upper, rhythm_number, nargout=4)
        start_points = np.array(start_points[0])
        features = np.append(end_points, start_points)
        features = np.sort(features) - features.min()
        if len(features) == rhythm_number * 2:
            break
        else:
            print('重新输入。')
            time.sleep(3)

    return features


# Thread function
class get_env_thread(QThread):
    signal = pyqtSignal(float)

    def __init__(self, collector: collect_data):
        super(get_env_thread, self).__init__()
        self.collector = collector

    def run(self):
        self.collector.get_env_intensity()
        self.signal.emit(self.collector.env_intensity)


class process_data_thread(QThread):
    signal = pyqtSignal(int)

    def __init__(self, name, collector):
        super(process_data_thread, self).__init__()
        self.name = name
        self.collector = collector

    def run(self):
        gross_data = []
        for idx in range(measure_cnt):
            self.signal.emit(idx)
            features = get_features(self.collector)
            gross_data.append(features)
        gross_data = np.array(gross_data)
        add_modify(add_data=gross_data, add_name=self.name)
        self.signal.emit(10)


class certificate_user_thread(QThread):
    signal = pyqtSignal(int)

    def __init__(self, collector: collect_data, clf: one_class_svm):
        super(certificate_user_thread, self).__init__()
        self.collector = collector
        self.clf = clf

    def run(self):
        features = get_features(self.collector)
        yes_or_no = self.clf.predict_(uncertified_person=features)
        self.signal.emit(yes_or_no)


class delete_user_thread(QThread):
    signal = pyqtSignal()

    def __init__(self, name):
        super(delete_user_thread, self).__init__()
        self.drop_name = name

    def run(self):
        time.sleep(1)
        delete_modify(delete_name=self.drop_name)
        # self.textBrowser_2.append('删除成功.')
        self.signal.emit()


class modify_rythem_thread(QThread):
    signal = pyqtSignal(int)

    def __init__(self, name, collector):
        super(modify_rythem_thread, self).__init__()
        self.user_name = name
        self.collector = collector

    def run(self):
        # collect new data
        gross_data = []
        for idx in range(measure_cnt):
            self.signal.emit(idx)
            features = get_features(self.collector)
            gross_data.append(features)
        gross_data = np.array(gross_data)
        overlap_modify(add_data=gross_data, selected_name=self.user_name)


class operate(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        super(operate, self).__init__()
        self.newWindow = None
        self.setupUi(self)
        self.lineEdit.setEchoMode(QtWidgets.QLineEdit.Password)

        self.Com_Dict = {}
        self.port_list = list(serial.tools.list_ports.comports())
        for port in self.port_list:
            self.Com_Dict["%s" % port[0]] = "%s" % port[1]
            self.comboBox_4.addItem(port[0])
        self.ser = self.comboBox_4.currentText()
        self.collector = collect_data(port=self.ser, m_time=1)

        self.get_intensity_thread = None
        self.processing_thread = None
        self.certificate_thread = None
        self.delete_user_thread = None
        self.modify_rhythm_thread = None

        self.judge = False
        self.classify = one_class_svm()
        self.name_list = np.loadtxt('gross_name.csv', dtype=str).reshape(-1)
        self.raw_data = np.loadtxt('gross_features.csv')

        self.encrypt = encrypt()

    #   Slut function
    '''Root user authenticate'''

    def manage_certificate(self):
        with open("pin.txt", "rb") as f:
            pin = f.read()
        dec_pin = self.encrypt.decryption(pin)
        pin_enter = self.lineEdit.text()
        bytes_pin_enter = pin_enter.encode('UTF-8')
        if dec_pin == bytes_pin_enter:
            self.judge = True

        if not self.judge:
            self.textBrowser.setText("管理员验证失败！")
            self.lineEdit.clear()
        else:
            self.textBrowser.setText("管理员验证成功！")
            self.textBrowser.append("当前用户列表：")
            for _, item in enumerate(self.name_list):
                self.textBrowser.append(item)
                self.comboBox_3.addItem(item)
            self.comboBox_2.addItem("添加新用户")
            self.comboBox_2.addItem("删除用户")
            self.comboBox_2.addItem("重置密码")
        self.judge = False

    '''Get environmental intensity'''

    def get_intensity(self):
        self.collector = collect_data(port=self.ser, m_time=1)
        self.get_intensity_thread = get_env_thread(self.collector)
        self.get_intensity_thread.signal.connect(self.display_env_intensity)
        self.get_intensity_thread.start()

    '''Register'''

    def start_measure(self):
        name = self.lineEdit_2.text()
        self.processing_thread = process_data_thread(name=name, collector=self.collector)
        self.processing_thread.signal.connect(self.display_collect_data)
        self.processing_thread.start()

    '''Authenticate'''

    def start_certificate(self):
        self.certificate_thread = certificate_user_thread(collector=self.collector, clf=self.classify)
        self.certificate_thread.signal.connect(self.display_authenticate_result)
        self.certificate_thread.start()

    '''Delete user's information'''

    def delete_user(self):
        if self.comboBox_2.currentText() == "删除用户":
            self.textBrowser_2.setText("正在删除该用户信息...")
            drop_user = self.comboBox_3.currentText()
            self.delete_user_thread = delete_user_thread(name=drop_user)
            self.delete_user_thread.signal.connect(self.display_delete_info)
            self.delete_user_thread.start()

    '''Modify Information'''

    def modify_rhythm(self):
        if self.comboBox_2.currentText() == "重置密码":
            self.textBrowser_2.setText("准备开始进行密码重置...")
            user_name = self.comboBox_3.currentText()
            self.modify_rhythm_thread = modify_rythem_thread(name=user_name, collector=self.collector)
            self.modify_rhythm_thread.signal.connect(self.display_modify_info)
            self.modify_rhythm_thread.start()

    '''Open port'''

    def open_port(self):
        self.port_list = list(serial.tools.list_ports.comports())
        for port in self.port_list:
            self.Com_Dict["%s" % port[0]] = "%s" % port[1]
            self.comboBox_4.addItem(port[0])
        self.ser = self.comboBox_4.currentText()
        self.collector = collect_data(port=self.ser, m_time=1)
        self.textBrowser_3.setText(self.ser + "串口已打开")

    '''Port change'''

    def port_changed(self):
        self.textBrowser_3.append("串口改变")

    '''Plot series'''

    def plot_series(self):
        if self.pushButton_7.text() == '串口绘图器':
            self.pushButton_7.setText('关闭绘图器')
            plot_collector.ser.open()
            self.newWindow = plot_window()
            self.newWindow.show()
        else:
            self.pushButton_7.setText('串口绘图器')
            self.newWindow.close()

    #   Connecting function

    def display_env_intensity(self, intensity):
        self.textBrowser_3.setText("当前环境噪声：")
        self.collector.env_intensity = intensity
        self.textBrowser_3.append(str(intensity))

    def display_collect_data(self, cnt):
        if cnt == 10:
            self.classify.train_()
            self.textBrowser_2.append('训练完成！')
        else:
            self.textBrowser_2.append(f"正在进行第{cnt + 1}次数据录入：")
            self.progressBar.setProperty("value", 12.5 * (cnt + 1))

    def display_authenticate_result(self, result):
        if result == -1:
            self.textBrowser_4.setText('非法用户.')
        else:
            self.textBrowser_4.setText('合法用户.')

    def display_delete_info(self):
        self.textBrowser_2.append('删除成功.')
        self.classify.train_()

    def display_modify_info(self):
        self.textBrowser_2.append('重置成功.')
        self.classify.train_()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    my_pyqt_form = operate()
    my_pyqt_form.show()
    sys.exit(app.exec_())

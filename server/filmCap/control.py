import time
import RPi.GPIO as GPIO
from timeit import default_timer as timer
import logging
import collections
import multiprocessing


steps_per_rev = 4200.0
rev_per_sec = 1.0

class fcControl():
    light_pin = 2
    red_pin = 3
    yellow_pin = 4
    trigger_pin = 24
    trigger_pin_active = False
    speed = 100
    frame_advance_pct=50 #[%]  #This is the CUSHION - we advance 100 minus this amt after trigger

    def __init__(self):
        logging.info("fcControl()")
        GPIO.setmode(GPIO.BCM)
        self.light = lightControl(self.light_pin, True)
        self.redled = lightControl(self.red_pin)
        self.yellowled = lightControl(self.yellow_pin)
        self.motor = stepperControl()
        GPIO.setup(self.trigger_pin, GPIO.IN, pull_up_down = GPIO.PUD_UP if self.trigger_pin_active == False else GPIO.PUD_DOWN)
        self.motorstate = 0
        self.smart_motor = False
        self.smart_headroom = 25
        self.triggertime = 0
        self.qlen = 5
        self.triggertimes = collections.deque([],self.qlen)
        self.phototimes = collections.deque([],self.qlen)

    def light_on(self):
        self.light.on()
    def light_off(self):
        self.light.off()
    def red_on(self):
        self.redled.on()
    def red_off(self):
        self.redled.off()
    def yellow_on(self):
        self.yellowled.on()
    def yellow_off(self):
        self.yellowled.off()
    def yellow_is_on(self):
        return GPIO.input(self.yellow_pin)

    def cleanup(self):
        logging.info("Cleaning up GPIO")
        self.light.off()
        self.redled.off()
        self.yellowled.off()
        self.motor.stop()
        self.motor_sleep()
#        GPIO.cleanup()

    def motor_wake(self):
        self.motor.wake()
    def motor_sleep(self):
        self.motor.sleep()


    def motor_fwd(self, speed=False):
        if (not speed):
            speed = self.speed
        self.motor.fwd(speed)
        self.motorstate = 1
    def motor_rev(self, speed=False):
        if (not speed):
            speed = self.speed
        self.motor.rev(speed)
        self.motorstate = -1
    def motor_stop(self):
        self.motor.stop()
        self.triggertimes.clear()
        self.phototimes.clear()
        if self.motorstate:
            self.motor.center(self.trigger_pin, self.frame_advance_pct, self.motorstate)
        self.motorstate = 0
        self.motor.sleep()
    def calibrate(self):
        self.motor.center(self.trigger_pin, self.frame_advance_pct, 1)


    def end_photo(self):
        newtime = timer()
        phototime = newtime - self.triggertime
        self.phototimes.appendleft(phototime)

class lightControl:
    def __init__(self, pin, reversed=False):
	self.pin = pin
	self.reversed = reversed
	GPIO.setup(pin, GPIO.OUT)
	self.off()

    def on(self):
	GPIO.output( self.pin, not(self.reversed) )

    def off(self):
	GPIO.output( self.pin, self.reversed )

class stepperControl:
    #stepper motor control pins
    dir_pin = 18
#    ms1_pin = 22
#    ms2_pin = 23
    sleep_pin = 23
    pulse_pin = 17

    def __init__(self):
        logging.info("stepperControl()")

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.dir_pin, GPIO.OUT)
        GPIO.setup(self.pulse_pin, GPIO.OUT)
#        GPIO.setup(self.ms1_pin, GPIO.OUT)
#        GPIO.setup(self.ms2_pin, GPIO.OUT)
        GPIO.setup(self.sleep_pin, GPIO.OUT)
        dir=False
        GPIO.output(self.dir_pin, dir)
        GPIO.output(self.pulse_pin, False)
#        GPIO.output(self.ms1_pin, True)
#        GPIO.output(self.ms2_pin, False)
        GPIO.output(self.sleep_pin, True)
        hz=1.0/(steps_per_rev*rev_per_sec)
        self.p1 = GPIO.PWM(self.pulse_pin, hz)

    def wake(self):
        GPIO.output(self.sleep_pin, False)
        logging.debug("motor waking")
        time.sleep(.1)

    def sleep(self):
        GPIO.output(self.sleep_pin, True)
        logging.debug("motor sleeping")
        time.sleep(.1)

    def stop(self):
        self.p1.stop()
        GPIO.output(self.dir_pin, False)

    def change_frequency(self, speed=100):
        # TODO: 'speed' is ignored
        hz= steps_per_rev * rev_per_sec
        logging.debug("change_frequency: " + str(hz))
        self.p1.ChangeFrequency(hz)

    def fwd(self, speed=100):
        self.wake()
        self.p1.stop()
        time.sleep(.5)
        self.change_frequency(speed)
        GPIO.output(self.dir_pin, False)
        logging.debug("motor starting fwd")
        self.p1.start(20)

    def rev(self, speed=100):
        self.wake()
        self.p1.stop()
        time.sleep(.5)
        self.change_frequency(speed)
        GPIO.output(self.dir_pin, True)
        logging.debug("motor starting rev")
        self.p1.start(20)

    def fwdFrame(self, num=1):
        self.wake()
        logging.debug("fwdFrame "+str(num))
        self.windFrame(num)
        self.sleep()

    def windFrame(self, num=1):
        pin=self.pulse_pin  #directly accessing for speed
        hp = 0.5 / (rev_per_sec * steps_per_rev)
        for i in range (0, int(steps_per_rev*num)):
            GPIO.output(pin, True) #used instead of variable for speed
            time.sleep(hp)
            GPIO.output(pin, False) #used instead of variable for speed
            time.sleep(hp)
 
    def revFrame(self, num=1):  #winds back one more than necessary, then forward to properly frame
        logging.debug("revFrame "+str(num))
        self.wake()
        if num==1:
            GPIO.output(self.dir_pin, True)
            self.windFrame()
            GPIO.output(self.dir_pin, False)
        else:
            GPIO.output(self.dir_pin, True)
            self.windFrame(num+1)
            GPIO.output(self.dir_pin, False)
            time.sleep(.25)
            self.windFrame(1)
        self.sleep()

    def center(self, trigger_pin, pct, fromState):
        logging.debug("Center a frame")
        #to center a frame in the gate and position the projector
        #mechanism properly relative to the photo trigger (i.e. 'pct'
        #distance ahead of it. Winding film backwards doesn't position
        #correctly, so we need to bump ahead a frame to position after
        #rewinding
        hp = 0.5 / (rev_per_sec * steps_per_rev)

        while GPIO.input(trigger_pin) == False:   #if trigger is engaging,reverse NO, FORWARD until it's not
            GPIO.output(self.dir_pin, False) #True)
            GPIO.output(self.pulse_pin, True)
            time.sleep(hp)
            GPIO.output(self.pulse_pin, False)
            time.sleep(hp)
        time.sleep(.2)
        while GPIO.input(trigger_pin) == True:   #then forward until it is
            GPIO.output(self.dir_pin, False)
            GPIO.output(self.pulse_pin, True)
            time.sleep(hp)
            GPIO.output(self.pulse_pin, False)
            time.sleep(hp)
        if fromState==-1:                         #if we had been reversing, jump forward a frame
            self.windFrame(1)
            logging.debug("Winding 1 frame")
        stepsFwd=int(steps_per_rev*(100-pct)/100.0)
        GPIO.output(self.dir_pin, False)
        time.sleep(.01)
        logging.debug("Forward "+str(stepsFwd))
        for i in range(0,stepsFwd):         #now forward enough to leave a proper cushion
            GPIO.output(self.pulse_pin, True)
            time.sleep(hp)
            GPIO.output(self.pulse_pin, False)
            time.sleep(hp)

class MotorDriver(multiprocessing.Process):
    #a very simple class designed to stick frame-advance in another
    #process during captures, so a different core can handle it and it
    #won't delay photography - or vice versa
    pulse_pin = 17
    def __init__(self, cap_event, exit_event):
        super(MotorDriver, self).__init__()
        self.cap_event=cap_event
        self.exit_event=exit_event
        logging.debug("MotorDriverInit")
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pulse_pin, GPIO.OUT)
        
    def run(self):
        logging.debug("Motor Frame Advance Process running")
        try:
            while not self.exit_event.is_set():
                if self.cap_event.wait(2): 
                    self.fwdFrame(1)
        except KeyboardInterrupt:
            logging.debug("Motor Process killed via kbd")
        finally:
            logging.debug("Motor Frame Advance Process ending")
            
    def fwdFrame(self, num=1):
        pin=self.pulse_pin
        hp = 0.5 / (rev_per_sec * steps_per_rev)
        logging.debug("Fframe")
        for i in range (0,int(steps_per_rev*num)):
            GPIO.output(pin, True) #used instead of variable for speed
            time.sleep(hp) #again, directly entring num for speed
            GPIO.output(pin, False) #used instead of variable for speed
            time.sleep(hp)
        self.cap_event.clear()

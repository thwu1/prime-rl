"""Configuration for the mutation adequacy pipeline."""
import os

VERILATOR_CMD = "verilator"
VERILATOR_FLAGS = ["--cc", "-Wall", "--Mdir"]

RTL_SOURCE = "/app/rtl/alu.v"
TESTBENCH = "/app/tb/tb_alu.cpp"
MUTATIONS_DIR = "/app/mutations"
RESULTS_DIR = "/app/results"
BUILD_DIR = "/app/build"

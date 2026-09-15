C     Simple E5 driver for RADAU5 - single tolerance CSV output
      PROGRAM E5REF
      IMPLICIT REAL*8 (A-H,O-Z)
      PARAMETER (N=4,LWORK=4*N*N+12*N+20,LIWORK=3*N+20)
      DIMENSION Y(N),WORK(LWORK),IWORK(LIWORK)
      EXTERNAL FE5,JE5,SOLOUT
C
C --- Initial conditions
      X=0.0D0
      Y(1)=1.76D-3
      Y(2)=0.0D0
      Y(3)=0.0D0
      Y(4)=0.0D0
C
C --- Tolerance: high precision reference
      RTOL=1.0D-12
      ATOL=1.7D-24
      ITOL=0
      H=1.0D-6
C
C --- Solver settings
      IJAC=1
      MLJAC=N
      IMAS=0
      IOUT=0
C
      DO 5 I=1,20
        WORK(I)=0.D0
        IWORK(I)=0
 5    CONTINUE
C
C --- Integrate to 7 output times: 10, 1e3, 1e5, 1e7, 1e9, 1e11, 1e13
      XEND=10.0D0
      DO 10 I=1,7
        CALL RADAU5(N,FE5,X,Y,XEND,H,
     &    RTOL,ATOL,ITOL,
     &    JE5,IJAC,MLJAC,MUJAC,
     &    FE5,IMAS,MLMAS,MUMAS,
     &    SOLOUT,IOUT,
     &    WORK,LWORK,IWORK,LIWORK,RPAR,IPAR,IDID)
        WRITE(6,99) XEND,Y(1),Y(2),Y(3),Y(4)
 99     FORMAT(E24.16,4(1X,E24.16))
        XEND=XEND*100.D0
 10   CONTINUE
      END
C
      SUBROUTINE SOLOUT(NR,XOLD,X,Y,CONT,LRC,N,RPAR,IPAR,IRTRN)
      IMPLICIT REAL*8 (A-H,O-Z)
      DIMENSION Y(N),CONT(LRC)
      RETURN
      END
